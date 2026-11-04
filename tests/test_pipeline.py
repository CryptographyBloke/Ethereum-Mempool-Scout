"""End-to-end: fake node -> collector -> SQLite -> analysis -> report -> REST API."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from mempool_scout import analysis as A
from mempool_scout.api import create_app
from mempool_scout.collector import Collector, CollectorConfig
from mempool_scout.constants import WETH
from mempool_scout.report import write_report
from mempool_scout.storage import connect

from .fixtures import POOL, USDC, FakeEth, h, sandwich_block

TS = 1_700_000_000


@pytest.fixture()
def dataset(tmp_path):
    db = str(tmp_path / "scout.sqlite")
    blocks = {100: sandwich_block(100, TS)}
    collector = Collector(CollectorConfig(wss_url="wss://example.invalid", db_path=db, large_swap_eth=10))
    collector.eth = (FakeEth(blocks, {POOL: (WETH, USDC)}))
    collector.session_id = collector.store.start_session("test", "example.invalid", 1, "full", "test")
    # Session started 10 minutes before the block -> block is eligible after the 5 min warm-up.
    collector.store.conn.execute("UPDATE sessions SET started_ms=? WHERE id=?", (TS * 1000 - 600_000, collector.session_id))

    async def scenario():
        # Victim (h2) and the unrelated tx (h4) were public; the attacker's txs never hit the mempool.
        collector.on_pending(h(2))
        collector.on_pending(h(4))
        collector.store.conn.execute("UPDATE pending_tx SET first_seen_ms=?", (TS * 1000 - 3_500,))
        tx = await collector.eth.get_transaction(h(2))
        collector.handle_tx(h(2), tx, TS * 1000 - 3_500)
        await collector.process_block(100)

    asyncio.run(scenario())
    collector.store.close()
    return db


def test_reannounced_hash_keeps_first_sighting(tmp_path):
    collector = Collector(CollectorConfig(wss_url="wss://example.invalid", db_path=str(tmp_path / "x.sqlite")))
    collector.session_id = collector.store.start_session("t", "h", 1, "full", "t")

    async def go():
        collector.on_pending(h(9))
        first = collector.store.conn.execute("SELECT first_seen_ms FROM pending_tx").fetchone()[0]
        await asyncio.sleep(0.01)
        collector.on_pending(h(9))
        assert collector.store.conn.execute("SELECT first_seen_ms FROM pending_tx").fetchone()[0] == first
        assert collector.counters.hashes == 1 and collector.queue.qsize() == 1

    asyncio.run(go())


def test_collector_writes_expected_rows(dataset):
    c = connect(dataset)
    assert c.execute("SELECT COUNT(*) FROM block_tx").fetchone()[0] == 4
    assert c.execute("SELECT COUNT(*) FROM pool_swap").fetchone()[0] == 3
    s = dict(c.execute("SELECT * FROM sandwiches").fetchone())
    assert s["victim_hash"] == h(2) and s["profit_token"] == WETH
    assert s["gross_profit_eth"] == pytest.approx(0.4)
    kinds = {r[0] for r in c.execute("SELECT kind FROM alerts")}
    assert kinds == {"large_swap", "sandwich"}
    blk = c.execute("SELECT builder_tag FROM blocks").fetchone()[0]
    assert blk == "beaverbuild.org"


def test_analysis_metrics(dataset):
    c = connect(dataset)
    p = A.Params()
    o = A.overview(c, p)
    assert o["eligible_blocks"] == 1 and o["txs"] == 4
    assert o["public_txs"] == 2 and o["public_share"] == 0.5
    assert o["router_swaps"] == 1 and o["router_swap_public_share"] == 1.0
    assert o["sandwiches"] == 1 and o["sandwich_victim_public_share"] == 1.0

    e = A.exposure(c, p)
    assert e["public"] == {"swaps": 1, "sandwiched": 1, "rate": 1.0, "ci95": e["public"]["ci95"]}
    assert e["private"]["swaps"] == 0

    d = A.inclusion_delay(c, p)
    assert d["count"] == 2 and d["median_s"] == 3.5

    # A long warm-up excludes the block entirely.
    assert A.overview(c, A.Params(warmup_ms=3_600_000))["eligible_blocks"] == 0

    detail = A.block_detail(c, 100, p)
    roles = {t["hash"]: t["sandwich_role"] for t in detail["txs"]}
    assert roles[h(1)] == "front-run" and roles[h(2)] == "victim" and roles[h(3)] == "back-run"


def test_statistics_helpers():
    lo, hi = A.wilson_interval(10, 100)
    assert 0.05 < lo < 0.1 < hi < 0.18
    t = A.two_proportion_z_test(30, 100, 10, 100)
    assert t["z"] > 3 and t["p_value"] < 0.001
    assert A.two_proportion_z_test(0, 0, 1, 2) is None


def test_report(dataset, tmp_path):
    md = write_report(dataset, tmp_path / "out", A.Params())
    text = md.read_text()
    assert "RQ1" in text and "beaverbuild.org" in text and "50.0%" in text
    assert (tmp_path / "out" / "report.json").exists()


def test_api(dataset):
    client = TestClient(create_app(dataset, frontend_dir=None))
    assert client.get("/api/health").json()["head"] == 100
    assert client.get("/api/overview").json()["sandwiches"] == 1
    assert client.get("/api/blocks").json()[0]["number"] == 100
    assert len(client.get("/api/blocks/100").json()["txs"]) == 4
    assert client.get("/api/blocks/5").status_code == 404
    assert client.get("/api/sandwiches").json()[0]["victim_public"] == 1
    assert client.get("/api/swaps/large").json()[0]["hash"] == h(2)
    assert client.get(f"/api/tx/{h(2)}").json()["included"]["block_number"] == 100
    assert client.get("/api/tx/0x12").status_code == 400
    assert client.get("/api/builders").json()[0]["builder_tag"] == "beaverbuild.org"
    assert client.get("/api/exposure").json()["public"]["sandwiched"] == 1
    assert client.get("/api/visibility/timeseries").json()[0]["txs"] == 4
    assert len(client.get("/api/alerts").json()) == 2
