"""Sandwich-attack detection from pool-level Swap events.

The detector works on executed blocks, not on mempool calldata, because MEV bots
call pools through their own contracts and their calldata is not decodable.

Heuristic (in the spirit of Torres et al., USENIX Security 2021, and Qin et al.,
IEEE S&P 2022).  Inside one block and one pool, a triple of swaps
(front, victim, back) at transaction positions i < j < k is a sandwich when:

1. front and victim trade in the same direction, back trades in the opposite one;
2. front and back come from the same attacker, identified by the same EOA
   (``tx.from``) or the same bot contract (``tx.to``);
3. the victim transaction has a different sender and a different ``tx.to`` than
   the attacker;
4. the back-run sells roughly what the front-run bought
   (|sold - bought| / bought <= ``volume_tolerance``).

Gross profit is measured in the token the attacker started with:
``received_in_back - paid_in_front``.  Gas and direct builder payments
(coinbase transfers) are not included in gross profit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from eth_abi import decode as abi_decode

from .constants import UNISWAP_V2_SWAP_TOPIC, UNISWAP_V3_SWAP_TOPIC
from .utils import get, norm_addr, to_bytes, to_hex, to_int


@dataclass
class PoolSwap:
    """One Swap event, seen from the pool. Positive amount = token went INTO the pool."""

    tx_hash: str
    tx_index: int
    log_index: int
    pool: str
    protocol: str
    amount0: int
    amount1: int
    tx_from: str | None = None
    tx_to: str | None = None

    @property
    def zero_for_one(self) -> bool:
        """True if the trader sold token0 for token1."""
        return self.amount0 > 0

    def paid(self) -> int:
        """Amount the trader paid into the pool (input token)."""
        return self.amount0 if self.zero_for_one else self.amount1

    def received(self) -> int:
        """Amount the trader received from the pool (output token)."""
        return -(self.amount1 if self.zero_for_one else self.amount0)


@dataclass
class Sandwich:
    pool: str
    protocol: str
    front: PoolSwap
    victim: PoolSwap
    back: PoolSwap
    attacker: str
    # True -> the profit is denominated in the pool's token0, else token1
    profit_in_token0: bool
    gross_profit: int


def parse_swap_log(log: Any, tx_from: str | None = None, tx_to: str | None = None) -> PoolSwap | None:
    topics = get(log, "topics") or []
    if not topics:
        return None
    t0 = to_hex(topics[0])
    data = to_bytes(get(log, "data"))
    try:
        if t0 == UNISWAP_V2_SWAP_TOPIC:
            a0_in, a1_in, a0_out, a1_out = abi_decode(["uint256"] * 4, data)
            amount0, amount1, protocol = a0_in - a0_out, a1_in - a1_out, "uniswap-v2"
        elif t0 == UNISWAP_V3_SWAP_TOPIC:
            amount0, amount1, _, _, _ = abi_decode(["int256", "int256", "uint160", "uint128", "int24"], data)
            protocol = "uniswap-v3"
        else:
            return None
    except Exception:
        return None
    if amount0 == 0 or (amount0 > 0) == (amount1 > 0):
        return None  # not a normal one-directional swap
    return PoolSwap(
        tx_hash=to_hex(get(log, "transactionHash")),
        tx_index=to_int(get(log, "transactionIndex")),
        log_index=to_int(get(log, "logIndex")),
        pool=norm_addr(get(log, "address")) or "",
        protocol=protocol,
        amount0=amount0,
        amount1=amount1,
        tx_from=tx_from,
        tx_to=tx_to,
    )


def extract_pool_swaps(receipts: Iterable[Any], txs_by_hash: dict[str, Any] | None = None) -> list[PoolSwap]:
    """Collect all V2/V3 Swap events from a block's receipts."""
    swaps: list[PoolSwap] = []
    for receipt in receipts:
        if to_int(get(receipt, "status"), 1) != 1:
            continue
        tx_hash = to_hex(get(receipt, "transactionHash"))
        tx = (txs_by_hash or {}).get(tx_hash)
        tx_from = norm_addr(get(receipt, "from")) or (norm_addr(get(tx, "from")) if tx else None)
        tx_to = norm_addr(get(receipt, "to")) or (norm_addr(get(tx, "to")) if tx else None)
        for log in get(receipt, "logs") or []:
            swap = parse_swap_log(log, tx_from, tx_to)
            if swap is not None:
                swaps.append(swap)
    return swaps


def _same_attacker(a: PoolSwap, b: PoolSwap) -> str | None:
    if a.tx_to and a.tx_to == b.tx_to:
        return a.tx_to
    if a.tx_from and a.tx_from == b.tx_from:
        return a.tx_from
    return None


def detect_sandwiches(swaps: Iterable[PoolSwap], volume_tolerance: float = 0.2) -> list[Sandwich]:
    by_pool: dict[str, list[PoolSwap]] = {}
    for s in swaps:
        by_pool.setdefault(s.pool, []).append(s)

    found: list[Sandwich] = []
    for pool, events in by_pool.items():
        events.sort(key=lambda s: (s.tx_index, s.log_index))
        seen_victims: set[str] = set()
        for fi, front in enumerate(events):
            for bi in range(fi + 1, len(events)):
                back = events[bi]
                if back.tx_index == front.tx_index or back.zero_for_one == front.zero_for_one:
                    continue
                attacker = _same_attacker(front, back)
                if attacker is None:
                    continue
                bought = front.received()
                sold = back.paid()
                if bought <= 0 or abs(sold - bought) / bought > volume_tolerance:
                    continue
                for victim in events[fi + 1 : bi]:
                    if victim.tx_index in (front.tx_index, back.tx_index):
                        continue
                    if victim.zero_for_one != front.zero_for_one:
                        continue
                    if victim.tx_from in (front.tx_from, back.tx_from) or victim.tx_to == attacker:
                        continue
                    if victim.tx_hash in seen_victims:
                        continue
                    seen_victims.add(victim.tx_hash)
                    found.append(Sandwich(
                        pool=pool,
                        protocol=front.protocol,
                        front=front,
                        victim=victim,
                        back=back,
                        attacker=attacker,
                        profit_in_token0=front.zero_for_one,
                        gross_profit=back.received() - front.paid(),
                    ))
                break  # the nearest matching back-run closes this front-run
    return found
