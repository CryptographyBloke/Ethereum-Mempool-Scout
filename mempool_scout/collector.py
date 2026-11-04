"""Async data collector.

Two WebSocket subscriptions run on one connection:

* ``newPendingTransactions`` — every announced hash is timestamped immediately
  (cheap, never dropped).  Details are fetched by a bounded worker pool; when the
  queue is full, the fetch is skipped but the timestamp is still kept, so the
  visibility measurement is not biased by RPC limits.
* ``newHeads`` — each new block is fetched with full transactions and receipts,
  matched against the mempool record, scanned for Uniswap V2/V3 Swap events and
  checked for sandwiches.

The session table records when the collector was running, so analysis only uses
blocks that were observed with a warmed-up mempool view.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .constants import KNOWN_ROUTERS, TOKEN0_SELECTOR, TOKEN1_SELECTOR, WETH
from .decoders import decode_swap_tx
from .rpc import EthRpc, WsRpcClient
from .sandwich import Sandwich, detect_sandwiches, extract_pool_swaps
from .storage import Store
from .utils import decode_builder_tag, get, norm_addr, now_ms, to_bytes, to_hex, to_int

log = logging.getLogger("mempool_scout")


@dataclass
class CollectorConfig:
    wss_url: str
    db_path: str = "data/scout.sqlite"
    vantage: str = "default"
    fetch_mode: str = "full"            # "full" = fetch tx details, "hash" = timestamps only
    full_pending_objects: bool = False  # ask the node to push full tx objects (geth / some providers)
    workers: int = 32
    queue_size: int = 20_000
    large_swap_eth: float = 10.0
    sandwich_volume_tolerance: float = 0.2
    stats_interval_s: int = 30
    commit_interval_s: float = 1.0
    receipts: bool = True
    routers: dict[str, str] = field(default_factory=lambda: dict(KNOWN_ROUTERS))


@dataclass
class Counters:
    hashes: int = 0
    fetched: int = 0
    fetch_skipped: int = 0
    fetch_missing: int = 0
    fetch_errors: int = 0
    swaps: int = 0
    large_swaps: int = 0
    deploys: int = 0
    blocks: int = 0
    sandwiches: int = 0


def tx_details(tx: Any) -> dict[str, Any]:
    to = norm_addr(get(tx, "to"))
    data = to_bytes(get(tx, "input") or get(tx, "data"))
    max_fee = get(tx, "maxFeePerGas")
    max_prio = get(tx, "maxPriorityFeePerGas")
    return {
        "sender": norm_addr(get(tx, "from")),
        "to": to,
        "nonce": to_int(get(tx, "nonce")),
        "value": to_int(get(tx, "value")),
        "gas": to_int(get(tx, "gas")),
        "type": to_int(get(tx, "type")),
        "gas_price": to_int(get(tx, "gasPrice")) if get(tx, "gasPrice") is not None else None,
        "max_fee": None if max_fee is None else to_int(max_fee),
        "max_priority_fee": None if max_prio is None else to_int(max_prio),
        "input_len": len(data),
        "is_deploy": to is None,
    }


class Collector:
    def __init__(self, cfg: CollectorConfig):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.counters = Counters()
        self.session_id: int | None = None
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=cfg.queue_size)
        self.block_queue: asyncio.Queue[int] = asyncio.Queue()
        self.eth: Any = None  # EthRpc (or a test double with the same methods)

    # ── mempool ───────────────────────────────────────────────────────────
    def on_pending(self, result: Any) -> None:
        seen = now_ms()
        if isinstance(result, (str, bytes, bytearray)):
            tx_hash, tx_obj = to_hex(result), None
        else:
            tx_hash, tx_obj = to_hex(get(result, "hash")), result
        if not self.store.record_pending_hash(tx_hash, seen, self.session_id):
            return  # re-announcement: keep the first sighting, do not fetch again
        self.counters.hashes += 1
        if tx_obj is not None:
            self.handle_tx(tx_hash, tx_obj, seen)
        elif self.cfg.fetch_mode == "full":
            try:
                self.queue.put_nowait((tx_hash, seen))
            except asyncio.QueueFull:
                self.counters.fetch_skipped += 1

    async def fetch_worker(self) -> None:
        while True:
            tx_hash, seen = await self.queue.get()
            try:
                tx = await self.eth.get_transaction(tx_hash)
                self.handle_tx(tx_hash, tx, seen)
            except Exception as e:  # dropped / already mined / rate-limited
                msg = str(e).lower()
                if "not found" in msg or "does not exist" in msg:
                    self.counters.fetch_missing += 1
                else:
                    self.counters.fetch_errors += 1
                    log.debug("fetch %s failed: %s", tx_hash, e)
            finally:
                self.queue.task_done()

    def handle_tx(self, tx_hash: str, tx: Any, seen_ms: int) -> None:
        if tx is None:
            self.counters.fetch_missing += 1
            return
        d = tx_details(tx)
        self.counters.fetched += 1
        self.store.record_pending_details(tx_hash, d)
        if d["is_deploy"]:
            self.counters.deploys += 1
            self.store.record_alert("deploy", tx_hash, {"sender": d["sender"], "bytecode_len": d["input_len"],
                                                        "gas": d["gas"], "nonce": d["nonce"]})
            log.info("contract deploy  from=%s  bytecode=%dB  hash=%s", d["sender"], d["input_len"], tx_hash)
            return
        intents = decode_swap_tx(tx, self.cfg.routers)
        if not intents:
            return
        self.counters.swaps += 1
        router = d["to"] or ""
        self.store.record_swap_intents(tx_hash, self.cfg.routers.get(router, router), intents, "mempool", seen_ms)
        notional = max((i.eth_notional_wei or 0) for i in intents)
        if notional >= self.cfg.large_swap_eth * 1e18:
            self.counters.large_swaps += 1
            first = intents[0]
            payload = {
                "function": first.function, "router": self.cfg.routers.get(router, router),
                "token_in": first.token_in, "token_out": first.token_out,
                "eth_notional": notional / 1e18, "sender": d["sender"],
                "max_priority_fee_gwei": None if d["max_priority_fee"] is None else d["max_priority_fee"] / 1e9,
            }
            self.store.record_alert("large_swap", tx_hash, payload)
            log.info("large swap  %.2f ETH  %s  %s", notional / 1e18, first.function, tx_hash)

    # ── blocks ────────────────────────────────────────────────────────────
    def on_head(self, result: Any) -> None:
        self.block_queue.put_nowait(to_int(get(result, "number")))

    async def block_worker(self) -> None:
        while True:
            number = await self.block_queue.get()
            try:
                await self.process_block(number)
            except Exception as e:
                log.warning("block %s failed: %s", number, e)
            finally:
                self.block_queue.task_done()

    async def _receipts(self, number: int, txs: list[Any]) -> list[Any]:
        try:
            receipts = await self.eth.get_block_receipts(number)
            if receipts is not None:
                return list(receipts)
        except Exception as e:
            log.debug("eth_getBlockReceipts failed (%s); falling back to per-tx receipts", e)
        sem = asyncio.Semaphore(16)

        async def one(h: Any) -> Any:
            async with sem:
                return await self.eth.get_transaction_receipt(to_hex(h))

        return list(await asyncio.gather(*(one(get(t, "hash")) for t in txs)))

    async def pool_tokens(self, pool: str) -> tuple[str, str] | None:
        cached = self.store.get_pool_tokens(pool)
        if cached:
            return cached
        try:
            t0 = await self.eth.call({"to": pool, "data": TOKEN0_SELECTOR})
            t1 = await self.eth.call({"to": pool, "data": TOKEN1_SELECTOR})
            tokens = ("0x" + bytes(t0)[-20:].hex(), "0x" + bytes(t1)[-20:].hex())
        except Exception:
            return None
        self.store.set_pool_tokens(pool, *tokens)
        return tokens

    async def fetch_block(self, number: int, attempts: int = 5) -> tuple[Any, list[Any]]:
        """Fetch a block and its receipts, retrying while the node (or a node behind a
        load balancer) has not caught up yet, and checking both come from the same block."""
        delay = 0.5
        for attempt in range(attempts):
            try:
                block = await self.eth.get_block(number, full_transactions=True)
                if block is None:
                    raise LookupError(f"block {number} not available yet")
                txs = list(get(block, "transactions") or [])
                receipts = await self._receipts(number, txs) if self.cfg.receipts else []
                if self.cfg.receipts:
                    if len(receipts) != len(txs) or any(r is None for r in receipts):
                        raise LookupError("incomplete receipts")
                    block_hash = to_hex(get(block, "hash"))
                    if receipts and to_hex(get(receipts[0], "blockHash") or get(block, "hash")) != block_hash:
                        raise LookupError("receipts belong to a different block (re-org or lagging node)")
                return block, receipts
            except Exception as e:
                if attempt == attempts - 1:
                    raise
                log.debug("block %s attempt %d failed: %s", number, attempt + 1, e)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    async def process_block(self, number: int) -> None:
        received = now_ms()
        block, receipts = await self.fetch_block(number)
        txs = list(get(block, "transactions") or [])
        rc_by_hash = {to_hex(get(r, "transactionHash")): r for r in receipts}
        base_fee = get(block, "baseFeePerGas")
        base_fee = None if base_fee is None else to_int(base_fee)

        rows: list[dict[str, Any]] = []
        txs_by_hash: dict[str, Any] = {}
        for t in txs:
            h = to_hex(get(t, "hash"))
            txs_by_hash[h] = t
            rc = rc_by_hash.get(h)
            egp = to_int(get(rc, "effectiveGasPrice")) if rc is not None and get(rc, "effectiveGasPrice") is not None else None
            intents = decode_swap_tx(t, self.cfg.routers)
            if intents and not self.store.has_swap_intent(h):
                # Swaps that never appeared in our mempool view are decoded from the block.
                to = norm_addr(get(t, "to")) or ""
                self.store.record_swap_intents(h, self.cfg.routers.get(to, to), intents, "block", None)
            rows.append({
                "hash": h,
                "tx_index": to_int(get(t, "transactionIndex")),
                "sender": norm_addr(get(t, "from")),
                "to": norm_addr(get(t, "to")),
                "type": to_int(get(t, "type")),
                "value": to_int(get(t, "value")),
                "status": to_int(get(rc, "status"), 1) if rc is not None else None,
                "gas_used": to_int(get(rc, "gasUsed")) if rc is not None else None,
                "effective_gas_price": egp,
                "priority_fee": (egp - base_fee) if egp is not None and base_fee is not None else None,
                "is_router_swap": bool(intents),
                "is_deploy": get(t, "to") is None,
            })

        pool_swaps = extract_pool_swaps(receipts, txs_by_hash)
        found = detect_sandwiches(pool_swaps, self.cfg.sandwich_volume_tolerance)
        enriched: list[tuple[Sandwich, str | None, float | None]] = []
        for sw in found:
            tokens = await self.pool_tokens(sw.pool)
            token = None if tokens is None else (tokens[0] if sw.profit_in_token0 else tokens[1])
            profit_eth = sw.gross_profit / 1e18 if token == WETH else None
            enriched.append((sw, token, profit_eth))
            self.store.record_alert("sandwich", sw.victim.tx_hash, {
                "block": number, "pool": sw.pool, "attacker": sw.attacker,
                "front": sw.front.tx_hash, "back": sw.back.tx_hash, "gross_profit_eth": profit_eth,
            })

        self.store.replace_block({
            "number": number,
            "hash": to_hex(get(block, "hash")),
            "parent_hash": to_hex(get(block, "parentHash")),
            "timestamp": to_int(get(block, "timestamp")),
            "fee_recipient": norm_addr(get(block, "miner")),
            "builder_tag": decode_builder_tag(get(block, "extraData")),
            "base_fee": base_fee,
            "gas_used": to_int(get(block, "gasUsed")),
            "gas_limit": to_int(get(block, "gasLimit")),
            "tx_count": len(txs),
            "received_ms": received,
            "session_id": self.session_id,
        }, rows, pool_swaps, enriched)
        self.store.commit()
        self.counters.blocks += 1
        self.counters.sandwiches += len(found)

        seen = self.store.conn.execute(
            "SELECT COUNT(*) FROM block_tx t JOIN pending_tx p ON p.hash = t.hash "
            "WHERE t.block_number = ? AND p.first_seen_ms < ?", (number, to_int(get(block, "timestamp")) * 1000)
        ).fetchone()[0]
        share = seen / len(txs) * 100 if txs else 0.0
        log.info("block %s  builder=%s  txs=%d  public=%.1f%%  sandwiches=%d",
                 f"{number:,}", decode_builder_tag(get(block, "extraData"))[:24], len(txs), share, len(found))

    # ── housekeeping ──────────────────────────────────────────────────────
    async def periodic(self) -> None:
        last_stats = now_ms()
        while True:
            await asyncio.sleep(self.cfg.commit_interval_s)
            if self.session_id is not None:
                self.store.heartbeat(self.session_id)
            self.store.commit()
            if now_ms() - last_stats >= self.cfg.stats_interval_s * 1000:
                last_stats = now_ms()
                c = self.counters
                log.info("stats  hashes=%s fetched=%s skipped=%s swaps=%s large=%s deploys=%s blocks=%s "
                         "sandwiches=%s queue=%d", f"{c.hashes:,}", f"{c.fetched:,}", f"{c.fetch_skipped:,}",
                         c.swaps, c.large_swaps, c.deploys, c.blocks, c.sandwiches, self.queue.qsize())

    async def _consume(self, queue: asyncio.Queue, handler: Any) -> None:
        while True:
            item = await queue.get()
            if item is None:  # connection closed
                return
            handler(item)

    async def run_once(self) -> None:
        cfg = self.cfg
        async with WsRpcClient(cfg.wss_url) as client:
            self.eth = EthRpc(client)
            chain_id = await self.eth.chain_id()
            head = await self.eth.block_number()
            self.session_id = self.store.start_session(cfg.vantage, urlparse(cfg.wss_url).hostname or "?",
                                                       chain_id, cfg.fetch_mode, __version__)
            log.info("connected chain_id=%s head=%s session=%s", chain_id, f"{head:,}", self.session_id)
            if chain_id != 1:
                log.warning("chain_id=%s: router addresses in constants.py are for Ethereum mainnet", chain_id)

            # Send exactly ["newPendingTransactions"] (or with `true`): some nodes accept an
            # explicit `false` but then never deliver notifications.
            pending_args = ("newPendingTransactions", True) if cfg.full_pending_objects else ("newPendingTransactions",)
            _, pending_q = await client.subscribe(*pending_args)
            _, heads_q = await client.subscribe("newHeads")
            tasks = [
                asyncio.create_task(self.periodic()),
                asyncio.create_task(self.block_worker()),
                asyncio.create_task(self._consume(pending_q, self.on_pending)),
                asyncio.create_task(self._consume(heads_q, self.on_head)),
            ]
            if cfg.fetch_mode == "full" and not cfg.full_pending_objects:
                tasks += [asyncio.create_task(self.fetch_worker()) for _ in range(cfg.workers)]
            try:
                await client.closed.wait()
                raise ConnectionError("WebSocket connection closed")
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.store.end_session(self.session_id)
                self.session_id = None
                if client.dropped_notifications:
                    log.warning("dropped %d notifications (consumer too slow)", client.dropped_notifications)

    async def run(self) -> None:
        """Run forever, reconnecting with exponential back-off.  Each connection is
        a separate session so gaps in coverage are explicit in the data."""
        delay = 2.0
        while True:
            started = now_ms()
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("connection lost: %s", e)
            if now_ms() - started > 60_000:
                delay = 2.0
            log.info("reconnecting in %.0fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120.0)


def run_collector(cfg: CollectorConfig) -> None:
    collector = Collector(cfg)

    async def main() -> None:
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, task.cancel)  # type: ignore[union-attr]
            except NotImplementedError:  # Windows
                pass
        try:
            await collector.run()
        except asyncio.CancelledError:
            log.info("shutting down")

    try:
        asyncio.run(main())
    finally:
        c = collector.counters
        log.info("final  hashes=%s fetched=%s swaps=%s large=%s deploys=%s blocks=%s sandwiches=%s",
                 f"{c.hashes:,}", f"{c.fetched:,}", c.swaps, c.large_swaps, c.deploys, c.blocks, c.sandwiches)
        collector.store.close()
