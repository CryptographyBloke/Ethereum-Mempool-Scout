"""Price a pending swap at the moment it is first seen, to measure slippage tolerance.

For an exact-input swap the user fixes ``amountIn`` and a minimum output
``amountOutMin``.  Quoting the same trade against current pool state gives the
expected output, so

    slippage tolerance = 1 - amountOutMin / expected_out

is how much worse than the current price the user agreed to accept.  That
headroom is exactly what a sandwich attacker can extract, which makes it the
natural explanatory variable for RQ2.

Quotes are ``eth_call``s against ``latest`` state:

* V2 paths: ``getAmountsOut(amountIn, path)`` on Uniswap V2 Router02 (or the
  SushiSwap router when the transaction targets it);
* V3 paths: ``quoteExactInput(path, amountIn)`` on Uniswap QuoterV2.

Exact-output swaps are not quoted (their bound is on the input side).
"""

from __future__ import annotations

from typing import Any

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from .decoders import SwapIntent

UNISWAP_V2_ROUTER02 = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
UNISWAP_V3_QUOTER_V2 = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"

GET_AMOUNTS_OUT = keccak(text="getAmountsOut(uint256,address[])")[:4]
QUOTE_EXACT_INPUT = keccak(text="quoteExactInput(bytes,uint256)")[:4]


def encode_v3_path(tokens: list[str], fees: list[int]) -> bytes:
    if len(tokens) != len(fees) + 1:
        raise ValueError("V3 path needs one fee per hop")
    out = bytes.fromhex(tokens[0][2:])
    for fee, tok in zip(fees, tokens[1:]):
        out += fee.to_bytes(3, "big") + bytes.fromhex(tok[2:])
    return out


def quotable(intent: SwapIntent) -> bool:
    return (intent.exact_input and intent.amount_in is not None and intent.amount_in > 0
            and intent.amount_out is not None and len(intent.path) >= 2
            and intent.protocol in ("uniswap-v2", "uniswap-v3"))


def build_quote_call(intent: SwapIntent, tx_to: str | None = None, router_label: str = "") -> dict[str, str] | None:
    """Return the ``eth_call`` params that quote this intent, or None if not quotable."""
    if not quotable(intent):
        return None
    if intent.protocol == "uniswap-v2":
        router = tx_to if (tx_to and router_label.startswith("sushiswap")) else UNISWAP_V2_ROUTER02
        data = GET_AMOUNTS_OUT + abi_encode(["uint256", "address[]"], [intent.amount_in, intent.path])
        return {"to": router, "data": "0x" + data.hex()}
    data = QUOTE_EXACT_INPUT + abi_encode(["bytes", "uint256"],
                                          [encode_v3_path(intent.path, intent.fees), intent.amount_in])
    return {"to": UNISWAP_V3_QUOTER_V2, "data": "0x" + data.hex()}


def parse_quote(intent: SwapIntent, raw: bytes) -> int:
    if intent.protocol == "uniswap-v2":
        (amounts,) = abi_decode(["uint256[]"], raw)
        return int(amounts[-1])
    amount_out, _, _, _ = abi_decode(["uint256", "uint160[]", "uint32[]", "uint256"], raw)
    return int(amount_out)


def slippage_tolerance(amount_out_min: int, quote_out: int) -> float | None:
    """1 - min/quote.  Negative means the bound is above the current price."""
    if quote_out <= 0:
        return None
    return 1 - amount_out_min / quote_out


async def quote_intent(eth: Any, intent: SwapIntent, tx_to: str | None = None,
                       router_label: str = "") -> tuple[int | None, float | None, str | None]:
    """Returns (quote_out, tolerance, error).  Never raises."""
    call = build_quote_call(intent, tx_to, router_label)
    if call is None:
        return None, None, "not quotable"
    try:
        raw = await eth.call(call)
        quote = parse_quote(intent, raw)
    except Exception as e:  # pool missing, revert, RPC error
        return None, None, str(e)[:120] or type(e).__name__
    return quote, slippage_tolerance(intent.amount_out or 0, quote), None
