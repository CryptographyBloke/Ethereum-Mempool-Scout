"""SQLite storage shared by the collector (writer) and the API/report (readers).

WAL mode lets the collector write while the API reads.  Integers that can exceed
64 bits (wei amounts, token amounts) are stored as decimal TEXT; convenient REAL
ETH columns are added where analysis needs them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .decoders import SwapIntent
from .sandwich import PoolSwap, Sandwich
from .utils import now_ms

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms    INTEGER NOT NULL,
    heartbeat_ms  INTEGER NOT NULL,
    ended_ms      INTEGER,
    vantage       TEXT,
    endpoint_host TEXT,
    chain_id      INTEGER,
    fetch_mode    TEXT,
    version       TEXT
);

-- Every hash announced by the node's public mempool, with the time we first saw it.
CREATE TABLE IF NOT EXISTS pending_tx (
    hash             TEXT PRIMARY KEY,
    first_seen_ms    INTEGER NOT NULL,
    session_id       INTEGER,
    fetched          INTEGER NOT NULL DEFAULT 0,
    sender           TEXT,
    to_addr          TEXT,
    nonce            INTEGER,
    value_wei        TEXT,
    gas              INTEGER,
    tx_type          INTEGER,
    gas_price        TEXT,
    max_fee          TEXT,
    max_priority_fee TEXT,
    input_len        INTEGER,
    is_deploy        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pending_seen ON pending_tx(first_seen_ms);

CREATE TABLE IF NOT EXISTS swap_intent (
    hash             TEXT NOT NULL,
    idx              INTEGER NOT NULL,
    source           TEXT NOT NULL,          -- 'mempool' or 'block'
    router           TEXT,
    protocol         TEXT,
    function         TEXT,
    token_in         TEXT,
    token_out        TEXT,
    exact_input      INTEGER,
    amount_in        TEXT,
    amount_out       TEXT,
    path             TEXT,
    eth_notional_wei TEXT,
    eth_notional     REAL,
    seen_ms          INTEGER,
    PRIMARY KEY (hash, idx)
);
CREATE INDEX IF NOT EXISTS idx_swap_eth ON swap_intent(eth_notional);

CREATE TABLE IF NOT EXISTS blocks (
    number        INTEGER PRIMARY KEY,
    hash          TEXT,
    parent_hash   TEXT,
    timestamp     INTEGER,
    fee_recipient TEXT,
    builder_tag   TEXT,
    base_fee      TEXT,
    gas_used      INTEGER,
    gas_limit     INTEGER,
    tx_count      INTEGER,
    received_ms   INTEGER,
    session_id    INTEGER
);

CREATE TABLE IF NOT EXISTS block_tx (
    hash                TEXT PRIMARY KEY,
    block_number        INTEGER NOT NULL,
    tx_index            INTEGER,
    sender              TEXT,
    to_addr             TEXT,
    tx_type             INTEGER,
    value_wei           TEXT,
    status              INTEGER,
    gas_used            INTEGER,
    effective_gas_price TEXT,
    priority_fee        TEXT,
    priority_fee_gwei   REAL,
    is_router_swap      INTEGER,
    is_deploy           INTEGER
);
CREATE INDEX IF NOT EXISTS idx_block_tx_block ON block_tx(block_number);

CREATE TABLE IF NOT EXISTS pool_swap (
    block_number INTEGER NOT NULL,
    log_index    INTEGER NOT NULL,
    tx_hash      TEXT,
    tx_index     INTEGER,
    pool         TEXT,
    protocol     TEXT,
    amount0      TEXT,
    amount1      TEXT,
    PRIMARY KEY (block_number, log_index)
);

CREATE TABLE IF NOT EXISTS pools (
    address  TEXT PRIMARY KEY,
    token0   TEXT,
    token1   TEXT
);

CREATE TABLE IF NOT EXISTS sandwiches (
    victim_hash      TEXT NOT NULL,
    pool             TEXT NOT NULL,
    block_number     INTEGER NOT NULL,
    protocol         TEXT,
    front_hash       TEXT,
    back_hash        TEXT,
    attacker         TEXT,
    profit_token     TEXT,
    gross_profit     TEXT,
    gross_profit_eth REAL,
    PRIMARY KEY (victim_hash, pool)
);
CREATE INDEX IF NOT EXISTS idx_sandwich_block ON sandwiches(block_number);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ms INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    hash       TEXT,
    payload    TEXT
);
"""


def _s(v: int | None) -> str | None:
    return None if v is None else str(v)


def connect(path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    path = str(path)
    if readonly and path != ":memory:":
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.row_factory = sqlite3.Row
    return conn


class Store:
    """Write-side wrapper.  Callers decide when to ``commit()``."""

    def __init__(self, path: str | Path):
        self.conn = connect(path)

    # sessions ---------------------------------------------------------------
    def start_session(self, vantage: str, endpoint_host: str, chain_id: int, fetch_mode: str, version: str) -> int:
        t = now_ms()
        cur = self.conn.execute(
            "INSERT INTO sessions(started_ms, heartbeat_ms, vantage, endpoint_host, chain_id, fetch_mode, version)"
            " VALUES (?,?,?,?,?,?,?)",
            (t, t, vantage, endpoint_host, chain_id, fetch_mode, version),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def heartbeat(self, session_id: int) -> None:
        self.conn.execute("UPDATE sessions SET heartbeat_ms=? WHERE id=?", (now_ms(), session_id))

    def end_session(self, session_id: int) -> None:
        t = now_ms()
        self.conn.execute("UPDATE sessions SET heartbeat_ms=?, ended_ms=? WHERE id=?", (t, t, session_id))
        self.conn.commit()

    # mempool ----------------------------------------------------------------
    def record_pending_hash(self, tx_hash: str, seen_ms: int, session_id: int | None) -> bool:
        """Store the first sighting of a hash. Returns False if it was already known."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO pending_tx(hash, first_seen_ms, session_id) VALUES (?,?,?)",
            (tx_hash, seen_ms, session_id),
        )
        return cur.rowcount == 1

    def record_pending_details(self, tx_hash: str, d: dict[str, Any]) -> None:
        self.conn.execute(
            """UPDATE pending_tx SET fetched=1, sender=?, to_addr=?, nonce=?, value_wei=?, gas=?, tx_type=?,
                   gas_price=?, max_fee=?, max_priority_fee=?, input_len=?, is_deploy=? WHERE hash=?""",
            (d["sender"], d["to"], d["nonce"], _s(d["value"]), d["gas"], d["type"], _s(d["gas_price"]),
             _s(d["max_fee"]), _s(d["max_priority_fee"]), d["input_len"], int(d["is_deploy"]), tx_hash),
        )

    def record_swap_intents(self, tx_hash: str, router: str, intents: Iterable[SwapIntent], source: str,
                            seen_ms: int | None) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO swap_intent(hash, idx, source, router, protocol, function, token_in, token_out,
                   exact_input, amount_in, amount_out, path, eth_notional_wei, eth_notional, seen_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (tx_hash, i, source, router, s.protocol, s.function, s.token_in, s.token_out, int(s.exact_input),
                 _s(s.amount_in), _s(s.amount_out), json.dumps(s.path), _s(s.eth_notional_wei),
                 None if s.eth_notional_wei is None else s.eth_notional_wei / 1e18, seen_ms)
                for i, s in enumerate(intents)
            ],
        )

    def has_swap_intent(self, tx_hash: str) -> bool:
        return self.conn.execute("SELECT 1 FROM swap_intent WHERE hash=? LIMIT 1", (tx_hash,)).fetchone() is not None

    def record_alert(self, kind: str, tx_hash: str | None, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO alerts(created_ms, kind, hash, payload) VALUES (?,?,?,?)",
            (now_ms(), kind, tx_hash, json.dumps(payload)),
        )

    # blocks -----------------------------------------------------------------
    def replace_block(self, block: dict[str, Any], txs: list[dict[str, Any]], pool_swaps: list[PoolSwap],
                      sandwiches: list[tuple[Sandwich, str | None, float | None]]) -> None:
        """Insert a block and everything derived from it, replacing any earlier
        version at the same height (handles short re-orgs)."""
        n = block["number"]
        c = self.conn
        c.execute("DELETE FROM block_tx WHERE block_number=?", (n,))
        c.execute("DELETE FROM pool_swap WHERE block_number=?", (n,))
        c.execute("DELETE FROM sandwiches WHERE block_number=?", (n,))
        c.execute(
            """INSERT OR REPLACE INTO blocks(number, hash, parent_hash, timestamp, fee_recipient, builder_tag,
                   base_fee, gas_used, gas_limit, tx_count, received_ms, session_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (n, block["hash"], block["parent_hash"], block["timestamp"], block["fee_recipient"],
             block["builder_tag"], _s(block["base_fee"]), block["gas_used"], block["gas_limit"],
             block["tx_count"], block["received_ms"], block["session_id"]),
        )
        c.executemany(
            """INSERT OR REPLACE INTO block_tx(hash, block_number, tx_index, sender, to_addr, tx_type, value_wei,
                   status, gas_used, effective_gas_price, priority_fee, priority_fee_gwei, is_router_swap, is_deploy)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (t["hash"], n, t["tx_index"], t["sender"], t["to"], t["type"], _s(t["value"]), t["status"],
                 t["gas_used"], _s(t["effective_gas_price"]), _s(t["priority_fee"]),
                 None if t["priority_fee"] is None else t["priority_fee"] / 1e9,
                 int(t["is_router_swap"]), int(t["is_deploy"]))
                for t in txs
            ],
        )
        c.executemany(
            """INSERT OR REPLACE INTO pool_swap(block_number, log_index, tx_hash, tx_index, pool, protocol, amount0, amount1)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(n, s.log_index, s.tx_hash, s.tx_index, s.pool, s.protocol, str(s.amount0), str(s.amount1))
             for s in pool_swaps],
        )
        c.executemany(
            """INSERT OR REPLACE INTO sandwiches(victim_hash, pool, block_number, protocol, front_hash, back_hash,
                   attacker, profit_token, gross_profit, gross_profit_eth) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(sw.victim.tx_hash, sw.pool, n, sw.protocol, sw.front.tx_hash, sw.back.tx_hash, sw.attacker,
              token, str(sw.gross_profit), profit_eth) for sw, token, profit_eth in sandwiches],
        )

    # pools ------------------------------------------------------------------
    def get_pool_tokens(self, pool: str) -> tuple[str, str] | None:
        row = self.conn.execute("SELECT token0, token1 FROM pools WHERE address=?", (pool,)).fetchone()
        return (row["token0"], row["token1"]) if row else None

    def set_pool_tokens(self, pool: str, token0: str, token1: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO pools(address, token0, token1) VALUES (?,?,?)", (pool, token0, token1))

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
