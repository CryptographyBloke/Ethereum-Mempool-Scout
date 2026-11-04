"""Normalisation helpers.

JSON-RPC returns hex strings, while ABI decoding and tests use ``bytes`` and ints.
Everything stored or compared in this project goes
through these helpers so the rest of the code can rely on one representation:
lower-case ``0x`` hex strings for hashes/addresses and Python ``int`` for numbers.
"""

from __future__ import annotations

import time
from typing import Any, Mapping


def now_ms() -> int:
    return int(time.time() * 1000)


def to_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        s = value[2:] if value.startswith(("0x", "0X")) else value
        if len(s) % 2:
            s = "0" + s
        return bytes.fromhex(s)
    raise TypeError(f"cannot convert {type(value).__name__} to bytes")


def to_hex(value: Any) -> str:
    """Lower-case 0x-prefixed hex for bytes-like or hex-string input."""
    return "0x" + to_bytes(value).hex()


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith(("0x", "0X")) else int(value)
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(value, "big")
    return int(value)


def norm_addr(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.lower()
    return to_hex(value)


def get(obj: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Read a field from a dict or an attribute-style object."""
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key, default)


def decode_builder_tag(extra_data: Any) -> str:
    """Best-effort human readable builder tag from a block's ``extraData``."""
    raw = to_bytes(extra_data)
    text = raw.decode("utf-8", errors="ignore")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    return text or "(none)"


def wei_to_eth(wei: int | None) -> float | None:
    return None if wei is None else wei / 1e18
