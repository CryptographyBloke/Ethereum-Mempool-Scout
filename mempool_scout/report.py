"""Offline research report: Markdown + JSON written from the SQLite dataset."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import analysis as A
from .storage import connect


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _sec(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


def _ts(ms: int | None) -> str:
    return "n/a" if not ms else datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_report(db_path: str | Path, params: A.Params, large_swap_eth: float = 10.0,
                 labels: str | None = None) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        return {
            "vantages": A.vantages(conn, params),
            "slippage": A.slippage(conn, params),
            "validation": A.precision_from_labels(labels) if labels else None,
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
        f"profit in WETH-denominated pools: {o['sandwich_gross_profit_eth']:.3f} ETH gross, "
        f"{o['sandwich_net_profit_eth']:.3f} ETH after gas",
        "",
        *_vantage_section(r["vantages"]),
        *_slippage_section(r["slippage"]),
        *_validation_section(r.get("validation")),
        "## Threats to validity",
        "",
        "* A single vantage point under-counts public transactions that never reached this node.",
        "* Sandwich detection is heuristic; net profit subtracts gas but not direct builder payments.",
        "* Only Uniswap V2/V3-style pools and the routers in `constants.py` are covered.",
        "",
    ]
    return "\n".join(lines)


def _vantage_section(v: dict[str, Any]) -> list[str]:
    lines = ["## RQ1b — How much does one vantage point miss?", ""]
    if len(v["per_vantage"]) < 2:
        return lines + ["Only one vantage point was recorded. Run a second collector "
                        "(`collect --mempool-only --vantage <name>`) on another provider to estimate this.", ""]
    u = v["union"]
    lines += [
        f"Blocks observed by all {len(v['vantages'])} vantages: {v['common_blocks']:,} ({v['txs']:,} transactions). "
        f"Union public share: **{_pct(u['public_share'])}**.",
        "",
        "| Vantage | Endpoint(s) | Public share | Under-estimate vs union | Seen only here | First to see | Median lag | Mean lag |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in v["per_vantage"]:
        under = "n/a" if p["underestimate_pp"] is None else f"{p['underestimate_pp']:.1f} pp"
        lag = "n/a" if p["avg_lag_ms"] is None else f"{p['avg_lag_ms']:.0f} ms"
        med = "n/a" if p["median_lag_ms"] is None else f"{p['median_lag_ms']:.0f} ms"
        lines.append(f"| {p['vantage']} | {p['endpoints']} | {_pct(p['public_share'])} | {under} | "
                     f"{p['exclusive']:,} | {_pct(p['first_seen_share'])} | {med} | {lag} |")
    return lines + [""]


def _slippage_section(s: dict[str, Any]) -> list[str]:
    lines = [
        "## RQ2b — Does a looser slippage tolerance predict being sandwiched?",
        "",
        f"Public, successful router swaps quoted when first seen: {s['quoted']:,} of "
        f"{s['public_router_swaps']:,} ({_pct(s['quote_coverage'])}).",
        "",
        "| Tolerance | Swaps | Sandwiched | Rate | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for b in s["buckets"]:
        ci = "n/a" if not b["ci95"] else f"{_pct(b['ci95'][0])} – {_pct(b['ci95'][1])}"
        lines.append(f"| {b['label']} | {b['swaps']:,} | {b['sandwiched']:,} | {_pct(b['rate'])} | {ci} |")
    tl = s["tight_vs_loose"]
    test = "n/a" if not tl["test"] else "z = {:.2f}, p = {:.3g}".format(tl["test"]["z"], tl["test"]["p_value"])
    med_s, med_o = s["median_tolerance_sandwiched"], s["median_tolerance_other"]
    lines += [
        "",
        f"* Loose (≥ {tl['threshold'] * 100:.1f}%) vs tight: {_pct(tl['loose']['rate'])} vs {_pct(tl['tight']['rate'])}; {test}",
        f"* Median tolerance: sandwiched {_pct(med_s, 2) if med_s is not None else 'n/a'}, "
        f"others {_pct(med_o, 2) if med_o is not None else 'n/a'}",
        "",
    ]
    return lines


def _validation_section(v: dict[str, Any] | None) -> list[str]:
    if not v:
        return []
    ci = "n/a" if not v["ci95"] else f"{_pct(v['ci95'][0])} – {_pct(v['ci95'][1])}"
    return ["## Detector validation", "",
            f"Manual labels: {v['true_positives']} true / {v['false_positives']} false positives "
            f"→ precision **{_pct(v['precision'])}** (95% CI {ci}).", ""]


def write_report(db_path: str | Path, out_dir: str | Path, params: A.Params, large_swap_eth: float = 10.0,
                 labels: str | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r = build_report(db_path, params, large_swap_eth, labels)
    (out / "report.json").write_text(json.dumps(r, indent=2, default=str))
    md = out / "report.md"
    md.write_text(render_markdown(r))
    return md
