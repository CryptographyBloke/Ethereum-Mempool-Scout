"""Multi-vantage storage, slippage quotes, migrations and detector validation."""

import asyncio
import csv
import sqlite3

import pytest
from eth_abi import decode, encode
from fastapi.testclient import TestClient

from mempool_scout import analysis as A
from mempool_scout.api import create_app
from mempool_scout.constants import WETH
from mempool_scout.decoders import SwapIntent
from mempool_scout.quotes import (GET_AMOUNTS_OUT, QUOTE_EXACT_INPUT, UNISWAP_V2_ROUTER02, UNISWAP_V3_QUOTER_V2,
                                  build_quote_call, encode_v3_path, parse_quote, quote_intent, slippage_tolerance)
from mempool_scout.storage import Store, connect
from mempool_scout.utils import now_ms

from .fixtures import DAI, USDC, h
from .test_pipeline import TS, dataset  # noqa: F401  (pytest fixture)

SUSHI = "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f"


# ── quotes ──────────────────────────────────────────────────────────────────
def v2_intent(**kw):
    base = dict(protocol="uniswap-v2", function="swapExactETHForTokens", token_in=WETH, token_out=USDC,
                exact_input=True, amount_in=10**18, amount_out=2_000 * 10**6, path=[WETH, USDC])
    return SwapIntent(**{**base, **kw})


def test_v2_quote_call_targets_router_and_encodes_path():
    call = build_quote_call(v2_intent())
    assert call["to"] == UNISWAP_V2_ROUTER02
    data = bytes.fromhex(call["data"][2:])
    assert data[:4] == GET_AMOUNTS_OUT
    amount, path = decode(["uint256", "address[]"], data[4:])
    assert amount == 10**18 and [a.lower() for a in path] == [WETH, USDC]
    # SushiSwap transactions are quoted on SushiSwap's own router
    assert build_quote_call(v2_intent(), SUSHI, "sushiswap-router")["to"] == SUSHI


def test_v3_quote_call_uses_quoter_with_packed_path():
    intent = SwapIntent("uniswap-v3", "exactInput", WETH, DAI, True, 10**18, 1, [WETH, USDC, DAI], [500, 100])
    call = build_quote_call(intent)
    assert call["to"] == UNISWAP_V3_QUOTER_V2
    data = bytes.fromhex(call["data"][2:])
    assert data[:4] == QUOTE_EXACT_INPUT
    path, amount = decode(["bytes", "uint256"], data[4:])
    assert path == encode_v3_path([WETH, USDC, DAI], [500, 100]) and amount == 10**18
    raw = encode(["uint256", "uint160[]", "uint32[]", "uint256"], [123, [1, 2], [3, 4], 99])
    assert parse_quote(intent, raw) == 123


def test_exact_output_and_unknown_amounts_are_not_quoted():
    assert build_quote_call(v2_intent(exact_input=False)) is None
    assert build_quote_call(v2_intent(amount_in=None)) is None


def test_slippage_tolerance():
    assert slippage_tolerance(99, 100) == pytest.approx(0.01)
    assert slippage_tolerance(101, 100) == pytest.approx(-0.01)
    assert slippage_tolerance(1, 0) is None


def test_quote_errors_are_returned_not_raised():
    class Boom:
        async def call(self, tx):
            raise RuntimeError("execution reverted")

    q, tol, err = asyncio.run(quote_intent(Boom(), v2_intent()))
    assert q is None and tol is None and "reverted" in err


# ── multi-vantage storage ───────────────────────────────────────────────────
def test_earliest_sighting_wins_across_vantages(tmp_path):
    st = Store(tmp_path / "m.sqlite")
    assert st.record_pending_hash(h(1), 2_000, 1, "a") == (True, True)
    assert st.record_pending_hash(h(1), 2_500, 1, "a") == (False, False)   # re-announcement
    assert st.record_pending_hash(h(1), 1_500, 2, "b") == (True, False)    # b saw it earlier, wrote later
    assert st.conn.execute("SELECT first_seen_ms FROM pending_tx").fetchone()[0] == 1_500
    rows = dict(st.conn.execute("SELECT vantage, first_seen_ms FROM pending_sighting").fetchall())
    assert rows == {"a": 2_000, "b": 1_500}


def test_migration_from_v1_database(tmp_path):
    path = tmp_path / "v1.sqlite"
    st = Store(path)
    sid = st.start_session("home", "node", 1, "full", "1.0")
    st.record_pending_hash(h(7), 1_000, sid, "home")
    c = st.conn
    c.execute("DELETE FROM pending_sighting")
    for col in ("fees", "quote_out", "slippage_tol", "quote_ms", "quote_error"):
        c.execute(f"ALTER TABLE swap_intent DROP COLUMN {col}")
    c.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    st.close()

    conn = connect(path)  # migrates
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert tuple(conn.execute("SELECT vantage, first_seen_ms FROM pending_sighting").fetchone()) == ("home", 1_000)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(swap_intent)")}
    assert {"quote_out", "slippage_tol"} <= cols


def test_full_collector_fetches_hashes_first_seen_by_a_mempool_only_vantage(tmp_path):
    from mempool_scout.collector import Collector, CollectorConfig

    db = str(tmp_path / "v.sqlite")
    first = Store(db)
    first.record_pending_hash(h(5), 1_000, None, "other")  # hash-only vantage saw it first
    first.close()
    c = Collector(CollectorConfig(wss_url="wss://x.invalid", db_path=db, vantage="primary"))

    async def go():
        c.on_pending(h(5))
        assert c.queue.qsize() == 1  # still fetched and decoded
        c.store.conn.execute("UPDATE pending_tx SET fetched=1")
        c.on_pending(h(6))
        c.store.record_pending_hash(h(7), 1_000, None, "other")
        c.store.conn.execute("UPDATE pending_tx SET fetched=1 WHERE hash=?", (h(7),))
        c.on_pending(h(7))
        assert c.queue.qsize() == 2  # h6 queued, h7 already fetched elsewhere

    asyncio.run(go())


# ── analyses on the end-to-end dataset ──────────────────────────────────────
@pytest.fixture()
def multi(dataset):  # noqa: F811
    """Add a second vantage 'b' that saw h4 earlier and the back-run h3, but not the victim h2."""
    st = Store(dataset)
    sid = st.start_session("b", "other.example", 1, "hash", "test")
    st.conn.execute("UPDATE sessions SET started_ms=? WHERE id=?", (TS * 1000 - 600_000, sid))
    st.record_pending_hash(h(4), TS * 1000 - 5_000, sid, "b")
    st.record_pending_hash(h(3), TS * 1000 - 1_000, sid, "b")
    st.close()
    return dataset


def test_vantage_comparison(multi):
    v = A.vantages(connect(multi), A.Params())
    assert v["vantages"] == ["b", "test"] and v["common_blocks"] == 1 and v["txs"] == 4
    assert v["union"]["public_txs"] == 3
    per = {p["vantage"]: p for p in v["per_vantage"]}
    assert per["test"]["public_txs"] == 2 and per["test"]["underestimate_pp"] == pytest.approx(25.0)
    assert per["test"]["exclusive"] == 1 and per["b"]["exclusive"] == 1
    assert per["b"]["first_seen_share"] == 1.0 and per["test"]["first_seen_share"] == 0.5
    assert per["test"]["avg_lag_ms"] == pytest.approx(750.0)  # h2: 0 ms, h4: 1500 ms behind b


def test_slippage_buckets(dataset):  # noqa: F811
    s = A.slippage(connect(dataset), A.Params())
    # The victim set amountOutMin = 1 against a quote of 100,000 USDC: ~100% tolerance.
    assert s["quoted"] == 1 and s["public_router_swaps"] == 1 and s["quote_coverage"] == 1.0
    loose = s["buckets"][-1]
    assert loose["label"] == "≥ 5%" and loose["swaps"] == 1 and loose["sandwiched"] == 1
    assert s["median_tolerance_sandwiched"] == pytest.approx(1.0)


def test_net_profit_subtracts_gas(dataset):  # noqa: F811
    [s] = A.sandwich_list(connect(dataset), A.Params())
    gas = (100_000 * 30e9 + 100_000 * 20e9) / 1e18  # front + back
    assert s["gas_cost_eth"] == pytest.approx(gas)
    assert s["net_profit_eth"] == pytest.approx(0.4 - gas)
    assert A.overview(connect(dataset), A.Params())["sandwich_net_profit_eth"] == pytest.approx(0.4 - gas)


def test_label_sample_and_precision(dataset, tmp_path):  # noqa: F811
    rows = A.label_sample(connect(dataset), n=10)
    assert len(rows) == 1 and rows[0]["victim_url"].endswith(h(2))
    path = tmp_path / "labels.csv"
    A.write_label_csv(rows * 4, str(path))
    with open(path) as f:
        data = list(csv.DictReader(f))
    for row, label in zip(data, ["TP", "tp", "FP", ""]):
        row["label"] = label
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=A.LABEL_FIELDS)
        w.writeheader()
        w.writerows(data)
    r = A.precision_from_labels(str(path))
    assert (r["true_positives"], r["false_positives"], r["unlabelled"]) == (2, 1, 1)
    assert r["precision"] == pytest.approx(2 / 3)


def test_research_endpoints(multi):
    client = TestClient(create_app(multi, frontend_dir=None))
    health = client.get("/api/health").json()
    assert {v["vantage"] for v in health["vantages"]} == {"test", "b"}
    assert client.get("/api/vantages").json()["union"]["public_txs"] == 3
    assert client.get("/api/slippage").json()["quoted"] == 1
    assert client.get("/api/sandwiches").json()[0]["net_profit_eth"] is not None


def test_sqlite_supports_drop_column():
    # The migration test relies on ALTER TABLE ... DROP COLUMN (SQLite >= 3.35).
    assert sqlite3.sqlite_version_info >= (3, 35, 0)
