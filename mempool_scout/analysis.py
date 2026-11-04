"""Metrics computed from the collected dataset.

Shared by the REST API (dashboard) and the offline ``report`` command, so the
numbers shown on the website and the numbers written into a paper come from the
same code.

Key definitions (see docs/methodology.md):

* **Eligible block** — a block received during a collector session, with a
  timestamp at least ``warmup_ms`` after the session started (the local mempool
  view is incomplete right after start-up).
* **Public transaction** — an included transaction whose hash our node announced
  before ``block.timestamp + grace_ms``.  Everything else is treated as *private*
  (sent through a private relay / builder RPC, or never reached our node).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass
class Params:
    warmup_ms: int = 5 * 60 * 1000
    grace_ms: int = 0

    def sql(self) -> dict[str, int]:
        return {"warmup_ms": self.warmup_ms, "grace_ms": self.grace_ms}


ELIGIBLE = """
WITH eb AS (
    SELECT b.* FROM blocks b JOIN sessions s ON s.id = b.session_id
    WHERE b.timestamp * 1000 >= s.started_ms + :warmup_ms
),
etx AS (
    SELECT t.*, eb.timestamp AS block_ts, eb.builder_tag, p.first_seen_ms,
           CASE WHEN p.first_seen_ms IS NOT NULL
                 AND p.first_seen_ms < eb.timestamp * 1000 + :grace_ms THEN 1 ELSE 0 END AS is_public
    FROM block_tx t
    JOIN eb ON eb.number = t.block_number
    LEFT JOIN pending_tx p ON p.hash = t.hash
)
"""


def _share(part: int | None, whole: int | None) -> float | None:
    return None if not whole else (part or 0) / whole


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_z_test(k1: int, n1: int, k2: int, n2: int) -> dict[str, float] | None:
    """Two-sided z-test for p1 == p2.  Returns z and p-value."""
    if n1 == 0 or n2 == 0:
        return None
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (k1 / n1 - k2 / n2) / se
    return {"z": z, "p_value": math.erfc(abs(z) / math.sqrt(2))}


def _one(conn: sqlite3.Connection, sql: str, params: dict[str, Any] | None = None) -> sqlite3.Row:
    return conn.execute(sql, params or {}).fetchone()


def _all(conn: sqlite3.Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params or {}).fetchall()]


# ── Overview ────────────────────────────────────────────────────────────────
def overview(conn: sqlite3.Connection, p: Params, large_swap_eth: float = 10.0) -> dict[str, Any]:
    q = p.sql()
    sess = _one(conn, """SELECT COUNT(*) n, MIN(started_ms) first_ms, MAX(heartbeat_ms) last_ms,
                                COALESCE(SUM(heartbeat_ms - started_ms), 0) runtime_ms FROM sessions""")
    mem = _one(conn, "SELECT COUNT(*) n, COALESCE(SUM(fetched), 0) fetched FROM pending_tx")
    blocks = _one(conn, "SELECT COUNT(*) n, MIN(number) lo, MAX(number) hi FROM blocks")
    vis = _one(conn, ELIGIBLE + """
        SELECT (SELECT COUNT(*) FROM eb) blocks,
               COUNT(*) txs, COALESCE(SUM(is_public), 0) public_txs,
               COALESCE(SUM(is_router_swap), 0) swaps,
               COALESCE(SUM(is_router_swap * is_public), 0) public_swaps
        FROM etx""", q)
    sw = _one(conn, ELIGIBLE + """
        SELECT COUNT(*) n, COUNT(DISTINCT s.attacker) attackers,
               COALESCE(SUM(s.gross_profit_eth), 0) profit_eth,
               COALESCE(SUM(CASE WHEN e.is_public = 1 THEN 1 ELSE 0 END), 0) public_victims
        FROM sandwiches s JOIN eb ON eb.number = s.block_number
        LEFT JOIN etx e ON e.hash = s.victim_hash""", q)
    large = _one(conn, "SELECT COUNT(DISTINCT hash) n FROM swap_intent WHERE source='mempool' AND eth_notional >= ?",
                 (large_swap_eth,))
    return {
        "sessions": sess["n"],
        "first_ms": sess["first_ms"],
        "last_ms": sess["last_ms"],
        "runtime_hours": sess["runtime_ms"] / 3_600_000,
        "pending_hashes": mem["n"],
        "pending_fetched": mem["fetched"],
        "blocks_stored": blocks["n"],
        "block_range": [blocks["lo"], blocks["hi"]],
        "eligible_blocks": vis["blocks"],
        "txs": vis["txs"],
        "public_txs": vis["public_txs"],
        "public_share": _share(vis["public_txs"], vis["txs"]),
        "router_swaps": vis["swaps"],
        "public_router_swaps": vis["public_swaps"],
        "router_swap_public_share": _share(vis["public_swaps"], vis["swaps"]),
        "sandwiches": sw["n"],
        "sandwich_attackers": sw["attackers"],
        "sandwich_gross_profit_eth": sw["profit_eth"],
        "sandwich_victims_public": sw["public_victims"],
        "sandwich_victim_public_share": _share(sw["public_victims"], sw["n"]),
        "large_swaps_seen": large["n"],
        "large_swap_threshold_eth": large_swap_eth,
        "params": {"warmup_ms": p.warmup_ms, "grace_ms": p.grace_ms},
    }


# ── Visibility ──────────────────────────────────────────────────────────────
def visibility_timeseries(conn: sqlite3.Connection, p: Params, bucket_s: int = 3600) -> list[dict[str, Any]]:
    rows = _all(conn, ELIGIBLE + """
        SELECT (block_ts / :bucket) * :bucket AS bucket_ts,
               COUNT(DISTINCT block_number) blocks,
               COUNT(*) txs, SUM(is_public) public_txs,
               SUM(is_router_swap) swaps, SUM(is_router_swap * is_public) public_swaps
        FROM etx GROUP BY bucket_ts ORDER BY bucket_ts""", {**p.sql(), "bucket": bucket_s})
    for r in rows:
        r["public_share"] = _share(r["public_txs"], r["txs"])
        r["swap_public_share"] = _share(r["public_swaps"], r["swaps"])
    return rows


def visibility_by_type(conn: sqlite3.Connection, p: Params) -> list[dict[str, Any]]:
    rows = _all(conn, ELIGIBLE + """
        SELECT COALESCE(tx_type, -1) tx_type, COUNT(*) txs, SUM(is_public) public_txs
        FROM etx GROUP BY tx_type ORDER BY txs DESC""", p.sql())
    for r in rows:
        r["public_share"] = _share(r["public_txs"], r["txs"])
    return rows


def builders(conn: sqlite3.Connection, p: Params, limit: int = 15) -> list[dict[str, Any]]:
    rows = _all(conn, ELIGIBLE + """
        , sw AS (SELECT block_number, COUNT(*) n FROM sandwiches GROUP BY block_number)
        SELECT eb.builder_tag, COUNT(*) blocks,
               SUM(x.txs) txs, SUM(x.public_txs) public_txs,
               SUM(x.swaps) swaps, SUM(x.public_swaps) public_swaps,
               COALESCE(SUM(sw.n), 0) sandwiches
        FROM eb
        JOIN (SELECT block_number, COUNT(*) txs, SUM(is_public) public_txs,
                     SUM(is_router_swap) swaps, SUM(is_router_swap * is_public) public_swaps
              FROM etx GROUP BY block_number) x ON x.block_number = eb.number
        LEFT JOIN sw ON sw.block_number = eb.number
        GROUP BY eb.builder_tag ORDER BY blocks DESC LIMIT :limit""", {**p.sql(), "limit": limit})
    total = sum(r["blocks"] for r in rows) or 1
    for r in rows:
        r["block_share"] = r["blocks"] / total
        r["public_share"] = _share(r["public_txs"], r["txs"])
        r["swap_public_share"] = _share(r["public_swaps"], r["swaps"])
    return rows


DELAY_EDGES_S = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256]


def inclusion_delay(conn: sqlite3.Connection, p: Params) -> dict[str, Any]:
    """Distribution of (block timestamp - first seen) for public transactions."""
    delays = [r[0] for r in conn.execute(ELIGIBLE + """
        SELECT block_ts * 1000 - first_seen_ms FROM etx WHERE is_public = 1""", p.sql())]
    delays.sort()
    bins = []
    for i, lo in enumerate(DELAY_EDGES_S):
        hi = DELAY_EDGES_S[i + 1] if i + 1 < len(DELAY_EDGES_S) else None
        n = sum(1 for d in delays if d >= lo * 1000 and (hi is None or d < hi * 1000))
        bins.append({"lo_s": lo, "hi_s": hi, "count": n})

    def q(f: float) -> float | None:
        return None if not delays else delays[min(len(delays) - 1, int(f * len(delays)))] / 1000

    return {"count": len(delays), "median_s": q(0.5), "p90_s": q(0.9), "p99_s": q(0.99), "bins": bins}


# ── Sandwich exposure (the headline research question) ──────────────────────
def exposure(conn: sqlite3.Connection, p: Params) -> dict[str, Any]:
    """Are publicly visible router swaps sandwiched more often than private ones?"""
    rows = {r["is_public"]: r for r in _all(conn, ELIGIBLE + """
        SELECT e.is_public, COUNT(*) swaps,
               SUM(CASE WHEN EXISTS (SELECT 1 FROM sandwiches s WHERE s.victim_hash = e.hash) THEN 1 ELSE 0 END) sandwiched
        FROM etx e WHERE e.is_router_swap = 1 AND e.status = 1 GROUP BY e.is_public""", p.sql())}
    out: dict[str, Any] = {}
    for key, flag in (("public", 1), ("private", 0)):
        r = rows.get(flag, {"swaps": 0, "sandwiched": 0})
        n, k = r["swaps"], r["sandwiched"] or 0
        ci = wilson_interval(k, n)
        out[key] = {"swaps": n, "sandwiched": k, "rate": _share(k, n), "ci95": list(ci) if ci else None}
    out["test"] = two_proportion_z_test(out["public"]["sandwiched"], out["public"]["swaps"],
                                        out["private"]["sandwiched"], out["private"]["swaps"])
    pr, vr = out["public"]["rate"], out["private"]["rate"]
    out["relative_risk"] = (pr / vr) if pr is not None and vr else None
    return out


# ── Lists used by the dashboard ─────────────────────────────────────────────
def recent_blocks(conn: sqlite3.Connection, p: Params, limit: int = 25, before: int | None = None) -> list[dict[str, Any]]:
    rows = _all(conn, """
        SELECT b.number, b.hash, b.timestamp, b.builder_tag, b.fee_recipient, b.tx_count, b.gas_used, b.base_fee,
               (SELECT COUNT(*) FROM block_tx t JOIN pending_tx pt ON pt.hash = t.hash
                 WHERE t.block_number = b.number AND pt.first_seen_ms < b.timestamp * 1000 + :grace_ms) public_txs,
               (SELECT COUNT(*) FROM block_tx t WHERE t.block_number = b.number) stored_txs,
               (SELECT COUNT(*) FROM block_tx t WHERE t.block_number = b.number AND t.is_router_swap = 1) swaps,
               (SELECT COUNT(*) FROM sandwiches s WHERE s.block_number = b.number) sandwiches
        FROM blocks b WHERE (:before IS NULL OR b.number < :before)
        ORDER BY b.number DESC LIMIT :limit""", {**p.sql(), "limit": limit, "before": before})
    for r in rows:
        r["public_share"] = _share(r["public_txs"], r["stored_txs"])
    return rows


def block_detail(conn: sqlite3.Connection, number: int, p: Params) -> dict[str, Any] | None:
    block = conn.execute("SELECT * FROM blocks WHERE number = ?", (number,)).fetchone()
    if block is None:
        return None
    block = dict(block)
    txs = _all(conn, """
        SELECT t.hash, t.tx_index, t.sender, t.to_addr, t.tx_type, t.value_wei, t.status, t.gas_used,
               t.priority_fee_gwei, t.is_router_swap, t.is_deploy, pt.first_seen_ms,
               CASE WHEN pt.first_seen_ms < :ts * 1000 + :grace_ms THEN 1 ELSE 0 END is_public,
               (SELECT function FROM swap_intent si WHERE si.hash = t.hash ORDER BY idx LIMIT 1) swap_function,
               (SELECT MAX(eth_notional) FROM swap_intent si WHERE si.hash = t.hash) eth_notional
        FROM block_tx t LEFT JOIN pending_tx pt ON pt.hash = t.hash
        WHERE t.block_number = :n ORDER BY t.tx_index""", {"n": number, "ts": block["timestamp"], "grace_ms": p.grace_ms})
    sws = _all(conn, "SELECT * FROM sandwiches WHERE block_number = ?", (number,))
    roles: dict[str, str] = {}
    for s in sws:
        roles[s["front_hash"]] = "front-run"
        roles[s["back_hash"]] = "back-run"
        roles[s["victim_hash"]] = "victim"
    for t in txs:
        t["sandwich_role"] = roles.get(t["hash"])
        t["inclusion_delay_s"] = (block["timestamp"] * 1000 - t["first_seen_ms"]) / 1000 if t["first_seen_ms"] else None
    block["txs"] = txs
    block["sandwiches"] = sws
    return block


def sandwich_list(conn: sqlite3.Connection, p: Params, limit: int = 50) -> list[dict[str, Any]]:
    return _all(conn, """
        SELECT s.*, b.timestamp, b.builder_tag, pt.first_seen_ms AS victim_first_seen_ms,
               CASE WHEN pt.first_seen_ms < b.timestamp * 1000 + :grace_ms THEN 1 ELSE 0 END victim_public,
               (SELECT function FROM swap_intent si WHERE si.hash = s.victim_hash ORDER BY idx LIMIT 1) victim_function,
               (SELECT MAX(eth_notional) FROM swap_intent si WHERE si.hash = s.victim_hash) victim_eth_notional
        FROM sandwiches s JOIN blocks b ON b.number = s.block_number
        LEFT JOIN pending_tx pt ON pt.hash = s.victim_hash
        ORDER BY s.block_number DESC LIMIT :limit""", {**p.sql(), "limit": limit})


def large_swaps(conn: sqlite3.Connection, min_eth: float = 10.0, limit: int = 50) -> list[dict[str, Any]]:
    rows = _all(conn, """
        SELECT si.hash, si.router, si.protocol, si.function, si.token_in, si.token_out, si.exact_input,
               si.amount_in, si.amount_out, si.eth_notional, si.seen_ms, si.path,
               t.block_number, t.tx_index,
               (SELECT COUNT(*) FROM sandwiches s WHERE s.victim_hash = si.hash) sandwiched
        FROM swap_intent si LEFT JOIN block_tx t ON t.hash = si.hash
        WHERE si.source = 'mempool' AND si.eth_notional >= :min_eth
        ORDER BY si.seen_ms DESC LIMIT :limit""", {"min_eth": min_eth, "limit": limit})
    for r in rows:
        r["path"] = json.loads(r["path"]) if r["path"] else []
    return rows


def tx_lookup(conn: sqlite3.Connection, tx_hash: str) -> dict[str, Any] | None:
    tx_hash = tx_hash.lower()
    pending = conn.execute("SELECT * FROM pending_tx WHERE hash = ?", (tx_hash,)).fetchone()
    included = conn.execute("SELECT * FROM block_tx WHERE hash = ?", (tx_hash,)).fetchone()
    if pending is None and included is None:
        return None
    intents = _all(conn, "SELECT * FROM swap_intent WHERE hash = ? ORDER BY idx", (tx_hash,))
    for i in intents:
        i["path"] = json.loads(i["path"]) if i["path"] else []
    sandwiches = _all(conn, """SELECT * FROM sandwiches WHERE victim_hash = :h OR front_hash = :h OR back_hash = :h""",
                      {"h": tx_hash})
    return {
        "hash": tx_hash,
        "pending": dict(pending) if pending else None,
        "included": dict(included) if included else None,
        "swap_intents": intents,
        "sandwiches": sandwiches,
    }


def alerts_since(conn: sqlite3.Connection, after_id: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    rows = _all(conn, "SELECT * FROM alerts WHERE id > ? ORDER BY id DESC LIMIT ?", (after_id, limit))
    for r in rows:
        r["payload"] = json.loads(r["payload"]) if r["payload"] else {}
    return rows
