"""Decode swap *intents* from router calldata.

A swap intent is what the user asked for (token in/out, amount, slippage bound)
as visible in the pending transaction, before execution.  Supported families:

* Uniswap V2 Router02 and forks (all 9 swap functions)
* Uniswap V3 SwapRouter and SwapRouter02 (single/multi-hop, exact in/out,
  including ``multicall`` wrappers)
* Uniswap Universal Router ``execute`` (V2/V3 swap commands)

Amounts are kept as raw integers in the token's own units.  ``eth_notional_wei``
is only filled in when one side of the trade is WETH/ETH, because converting
arbitrary tokens to ETH requires price data that calldata alone does not give.
This avoids the bug in v1 where token amounts were compared directly with an
ETH threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from eth_abi import decode as abi_decode
from eth_utils import keccak

from .constants import KNOWN_ROUTERS, WETH
from .utils import get, norm_addr, to_bytes, to_int

# Universal Router uses this sentinel to mean "use the router's whole balance".
CONTRACT_BALANCE = 1 << 255


@dataclass
class SwapIntent:
    protocol: str
    function: str
    token_in: str | None
    token_out: str | None
    # exact_input=True  -> amount_in is exact, amount_out is the minimum accepted
    # exact_input=False -> amount_out is exact, amount_in is the maximum accepted
    exact_input: bool
    amount_in: int | None
    amount_out: int | None
    path: list[str] = field(default_factory=list)
    fees: list[int] = field(default_factory=list)
    eth_notional_wei: int | None = None

    def finalize(self) -> "SwapIntent":
        if self.token_in == WETH and self.amount_in is not None:
            self.eth_notional_wei = self.amount_in
        elif self.token_out == WETH and self.amount_out is not None:
            self.eth_notional_wei = self.amount_out
        return self


def _sel(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def decode_v3_path(path: bytes) -> tuple[list[str], list[int]]:
    """Uniswap V3 packed path: token(20) [fee(3) token(20)]*."""
    if len(path) < 20 or (len(path) - 20) % 23:
        raise ValueError("malformed V3 path")
    tokens = ["0x" + path[0:20].hex()]
    fees: list[int] = []
    i = 20
    while i < len(path):
        fees.append(int.from_bytes(path[i : i + 3], "big"))
        tokens.append("0x" + path[i + 3 : i + 23].hex())
        i += 23
    return tokens, fees


# ── Uniswap V2 style ────────────────────────────────────────────────────────
# kind:  "in"      (amountIn, amountOutMin, path, ...)
#        "out"     (amountOut, amountInMax, path, ...)
#        "eth_in"  (amountOutMin, path, ...)   amountIn  = msg.value
#        "eth_out" (amountOut, path, ...)      amountInMax = msg.value
_V2_FUNCS: list[tuple[str, list[str], str]] = [
    ("swapExactTokensForTokens", ["uint256", "uint256", "address[]", "address", "uint256"], "in"),
    ("swapTokensForExactTokens", ["uint256", "uint256", "address[]", "address", "uint256"], "out"),
    ("swapExactETHForTokens", ["uint256", "address[]", "address", "uint256"], "eth_in"),
    ("swapTokensForExactETH", ["uint256", "uint256", "address[]", "address", "uint256"], "out"),
    ("swapExactTokensForETH", ["uint256", "uint256", "address[]", "address", "uint256"], "in"),
    ("swapETHForExactTokens", ["uint256", "address[]", "address", "uint256"], "eth_out"),
    ("swapExactTokensForTokensSupportingFeeOnTransferTokens", ["uint256", "uint256", "address[]", "address", "uint256"], "in"),
    ("swapExactETHForTokensSupportingFeeOnTransferTokens", ["uint256", "address[]", "address", "uint256"], "eth_in"),
    ("swapExactTokensForETHSupportingFeeOnTransferTokens", ["uint256", "uint256", "address[]", "address", "uint256"], "in"),
    # SwapRouter02 exposes V2 swaps without the deadline argument.
    ("swapExactTokensForTokens", ["uint256", "uint256", "address[]", "address"], "in"),
    ("swapTokensForExactTokens", ["uint256", "uint256", "address[]", "address"], "out"),
]


def _v2_decoder(name: str, types: list[str], kind: str) -> Callable[[bytes, int], list[SwapIntent]]:
    def decode(args: bytes, value: int) -> list[SwapIntent]:
        vals = abi_decode(types, args)
        if kind == "in":
            amount_in, amount_out, path = vals[0], vals[1], vals[2]
        elif kind == "out":
            amount_out, amount_in, path = vals[0], vals[1], vals[2]
        elif kind == "eth_in":
            amount_out, path, amount_in = vals[0], vals[1], value
        else:  # eth_out
            amount_out, path, amount_in = vals[0], vals[1], value
        path = [p.lower() for p in path]
        return [
            SwapIntent(
                protocol="uniswap-v2",
                function=name,
                token_in=path[0] if path else None,
                token_out=path[-1] if path else None,
                exact_input=kind in ("in", "eth_in"),
                amount_in=amount_in,
                amount_out=amount_out,
                path=path,
            ).finalize()
        ]

    return decode


# ── Uniswap V3 SwapRouter / SwapRouter02 ────────────────────────────────────
def _v3_single(name: str, with_deadline: bool, exact_in: bool):
    struct = "(address,address,uint24,address,uint256,uint256,uint256,uint160)" if with_deadline \
        else "(address,address,uint24,address,uint256,uint256,uint160)"

    def decode(args: bytes, value: int) -> list[SwapIntent]:
        (p,) = abi_decode([struct], args)
        token_in, token_out, fee = p[0].lower(), p[1].lower(), p[2]
        a, b = (p[5], p[6]) if with_deadline else (p[4], p[5])
        amount_in, amount_out = (a, b) if exact_in else (b, a)
        return [SwapIntent("uniswap-v3", name, token_in, token_out, exact_in, amount_in, amount_out,
                           [token_in, token_out], [fee]).finalize()]

    return f"{name}({struct})", decode


def _v3_multi(name: str, with_deadline: bool, exact_in: bool):
    struct = "(bytes,address,uint256,uint256,uint256)" if with_deadline else "(bytes,address,uint256,uint256)"

    def decode(args: bytes, value: int) -> list[SwapIntent]:
        (p,) = abi_decode([struct], args)
        tokens, fees = decode_v3_path(p[0])
        a, b = (p[3], p[4]) if with_deadline else (p[2], p[3])
        if exact_in:
            token_in, token_out, amount_in, amount_out = tokens[0], tokens[-1], a, b
        else:  # exact-output paths are encoded in reverse (tokenOut first)
            tokens, fees = tokens[::-1], fees[::-1]
            token_in, token_out, amount_out, amount_in = tokens[0], tokens[-1], a, b
        return [SwapIntent("uniswap-v3", name, token_in, token_out, exact_in, amount_in, amount_out,
                           tokens, fees).finalize()]

    return f"{name}({struct})", decode


# ── Universal Router ────────────────────────────────────────────────────────
UR_V3_SWAP_EXACT_IN = 0x00
UR_V3_SWAP_EXACT_OUT = 0x01
UR_V2_SWAP_EXACT_IN = 0x08
UR_V2_SWAP_EXACT_OUT = 0x09
UR_WRAP_ETH = 0x0B
UR_COMMAND_MASK = 0x3F


def _decode_universal(commands: bytes, inputs: list[bytes], value: int) -> list[SwapIntent]:
    out: list[SwapIntent] = []
    for i, raw_cmd in enumerate(commands):
        if i >= len(inputs):
            break
        cmd = raw_cmd & UR_COMMAND_MASK
        data = inputs[i]
        try:
            if cmd in (UR_V3_SWAP_EXACT_IN, UR_V3_SWAP_EXACT_OUT):
                _, a, b, path_bytes, _ = abi_decode(["address", "uint256", "uint256", "bytes", "bool"], data)
                tokens, fees = decode_v3_path(path_bytes)
                exact_in = cmd == UR_V3_SWAP_EXACT_IN
                if not exact_in:
                    tokens, fees = tokens[::-1], fees[::-1]
                amount_in, amount_out = (a, b) if exact_in else (b, a)
                name = "V3_SWAP_EXACT_IN" if exact_in else "V3_SWAP_EXACT_OUT"
            elif cmd in (UR_V2_SWAP_EXACT_IN, UR_V2_SWAP_EXACT_OUT):
                _, a, b, path, _ = abi_decode(["address", "uint256", "uint256", "address[]", "bool"], data)
                tokens, fees = [p.lower() for p in path], []
                exact_in = cmd == UR_V2_SWAP_EXACT_IN
                amount_in, amount_out = (a, b) if exact_in else (b, a)
                name = "V2_SWAP_EXACT_IN" if exact_in else "V2_SWAP_EXACT_OUT"
            else:
                continue
        except Exception:
            continue
        if amount_in == CONTRACT_BALANCE:
            # Router spends what it holds, typically ETH wrapped by a prior WRAP_ETH.
            amount_in = value if (tokens and tokens[0] == WETH and value) else None
        out.append(SwapIntent(
            protocol="uniswap-v3" if name.startswith("V3") else "uniswap-v2",
            function=f"universal:{name}",
            token_in=tokens[0] if tokens else None,
            token_out=tokens[-1] if tokens else None,
            exact_input=exact_in,
            amount_in=amount_in,
            amount_out=amount_out,
            path=tokens,
            fees=fees,
        ).finalize())
    return out


def _ur_execute_deadline(args: bytes, value: int) -> list[SwapIntent]:
    commands, inputs, _ = abi_decode(["bytes", "bytes[]", "uint256"], args)
    return _decode_universal(commands, list(inputs), value)


def _ur_execute(args: bytes, value: int) -> list[SwapIntent]:
    commands, inputs = abi_decode(["bytes", "bytes[]"], args)
    return _decode_universal(commands, list(inputs), value)


# ── Multicall wrappers (SwapRouter / SwapRouter02) ──────────────────────────
def _multicall(types: list[str]):
    def decode(args: bytes, value: int) -> list[SwapIntent]:
        calls = abi_decode(types, args)[-1]
        out: list[SwapIntent] = []
        for call in calls:
            out.extend(decode_calldata(call, value, _depth=1))
        return out

    return decode


_DECODERS: dict[bytes, Callable[[bytes, int], list[SwapIntent]]] = {}


def _register(signature: str, fn: Callable[[bytes, int], list[SwapIntent]]) -> None:
    _DECODERS[_sel(signature)] = fn


for _name, _types, _kind in _V2_FUNCS:
    _register(f"{_name}({','.join(_types)})", _v2_decoder(_name, _types, _kind))

for _with_deadline in (True, False):
    for _sig, _fn in (
        _v3_single("exactInputSingle", _with_deadline, True),
        _v3_single("exactOutputSingle", _with_deadline, False),
        _v3_multi("exactInput", _with_deadline, True),
        _v3_multi("exactOutput", _with_deadline, False),
    ):
        _register(_sig, _fn)

_register("execute(bytes,bytes[],uint256)", _ur_execute_deadline)
_register("execute(bytes,bytes[])", _ur_execute)
_register("multicall(bytes[])", _multicall(["bytes[]"]))
_register("multicall(uint256,bytes[])", _multicall(["uint256", "bytes[]"]))
_register("multicall(bytes32,bytes[])", _multicall(["bytes32", "bytes[]"]))


def supported_selectors() -> list[str]:
    return sorted("0x" + s.hex() for s in _DECODERS)


def decode_calldata(calldata: Any, value: int = 0, _depth: int = 0) -> list[SwapIntent]:
    """Decode router calldata into zero or more swap intents. Never raises."""
    data = to_bytes(calldata)
    if len(data) < 4 or _depth > 2:
        return []
    fn = _DECODERS.get(data[:4])
    if fn is None:
        return []
    try:
        return fn(data[4:], value)
    except Exception:
        return []


def decode_swap_tx(tx: Any, routers: dict[str, str] | None = None) -> list[SwapIntent]:
    """Decode a transaction if it targets a known router; otherwise return []."""
    routers = routers if routers is not None else KNOWN_ROUTERS
    to = norm_addr(get(tx, "to"))
    if to is None or to not in routers:
        return []
    return decode_calldata(get(tx, "input") or get(tx, "data"), to_int(get(tx, "value")))
