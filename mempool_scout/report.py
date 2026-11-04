"""Offline research report: Markdown + JSON written from the SQLite dataset."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import analysis as A
from .storage import connect


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _sec(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


def _ts(ms: int | None) -> str:
    return "n/a" if not ms else datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_report(db_path: str | Path, params: A.Params, large_swap_eth: float = 10.0) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overview": A.overview(conn, params, large_swap_eth),
            "visibility_by_type": A.visibility_by_type(conn, params),
            "builders": A.builders(conn, params, limit=20),
            "inclusion_delay": A.inclusion_delay(conn, params),
            "exposure": A.exposure(conn, params),
            "hourly": A.visibility_timeseries(conn, params, 3600),
        }
    finally:
        conn.close()


def render_markdown(r: dict[str, Any]) -> str:
    o, e, d = r["overview"], r["exposure"], r["inclusion_delay"]
    lines = [
        "# Mempool Scout — measurement report",
        "",
        f"Generated {r['generated_at']}.  Warm-up {o['params']['warmup_ms'] / 60000:.0f} min, "
        f"grace {o['params']['grace_ms']} ms.",
        "",
        "## Dataset",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Collection window | {_ts(o['first_ms'])} → {_ts(o['last_ms'])} |",
        f"| Sessions / runtime | {o['sessions']} / {o['runtime_hours']:.2f} h |",
        f"| Pending hashes observed | {o['pending_hashes']:,} |",
        f"| Blocks stored / eligible | {o['blocks_stored']:,} / {o['eligible_blocks']:,} |",
        f"| Transactions in eligible blocks | {o['txs']:,} |",
        "",
        "## RQ1 — How much of the block content was publicly visible?",
        "",
        f"* Public share of all included transactions: **{_pct(o['public_share'])}** "
        f"({o['public_txs']:,} / {o['txs']:,})",
        f"* Public share of Uniswap router swaps: **{_pct(o['router_swap_public_share'])}** "
        f"({o['public_router_swaps']:,} / {o['router_swaps']:,})",
        f"* Inclusion delay of public transactions: median {_sec(d['median_s'])}, p90 {_sec(d['p90_s'])}",
        "",
        "| Tx type | Txs | Public share |",
        "|---|---|---|",
        *[f"| {t['tx_type']} | {t['txs']:,} | {_pct(t['public_share'])} |" for t in r["visibility_by_type"]],
        "",
        "### By block builder (extraData tag)",
        "",
        "| Builder | Blocks | Block share | Public tx share | Public swap share | Sandwiches |",
        "|---|---|---|---|---|---|",
        *[f"| {b['builder_tag']} | {b['blocks']:,} | {_pct(b['block_share'])} | {_pct(b['public_share'])} | "
          f"{_pct(b['swap_public_share'])} | {b['sandwiches']} |" for b in r["builders"]],
        "",
        "## RQ2 — Are publicly visible swaps sandwiched more often?",
        "",
        "| Group | Router swaps | Sandwiched | Rate | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for key in ("public", "private"):
        g = e[key]
        ci = "n/a" if not g["ci95"] else f"{_pct(g['ci95'][0])} – {_pct(g['ci95'][1])}"
        lines.append(f"| {key} | {g['swaps']:,} | {g['sandwiched']:,} | {_pct(g['rate'])} | {ci} |")
    test = e.get("test")
    rr = e.get("relative_risk")
    rr_s = "n/a" if rr is None else f"{rr:.2f}"
    test_s = "n/a" if not test else "z = {:.2f}, p = {:.3g}".format(test["z"], test["p_value"])
    lines += [
        "",
        f"* Relative risk (public / private): {rr_s}",
        f"* Two-proportion z-test: {test_s}",
        f"* Sandwiches detected: {o['sandwiches']:,} by {o['sandwich_attackers']:,} attackers; "
        f"{_pct(o['sandwich_victim_public_share'])} of victims were publicly visible; "
        f"gross profit in WETH-denominated pools: {o['sandwich_gross_profit_eth']:.3f} ETH",
        "",
        "## Threats to validity",
        "",
        "* A single vantage point under-counts public transactions that never reached this node.",
        "* Sandwich detection is heuristic; gas and builder tips are not subtracted from profit.",
        "* Only Uniswap V2/V3-style pools and the routers in `constants.py` are covered.",
        "",
    ]
    return "\n".join(lines)


def write_report(db_path: str | Path, out_dir: str | Path, params: A.Params, large_swap_eth: float = 10.0) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r = build_report(db_path, params, large_swap_eth)
    (out / "report.json").write_text(json.dumps(r, indent=2, default=str))
    md = out / "report.md"
    md.write_text(render_markdown(r))
    return md
