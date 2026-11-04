"""Command-line entry point: ``mempool-scout collect | serve | report``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .analysis import Params
from .constants import KNOWN_ROUTERS


def _add_params(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=os.environ.get("SCOUT_DB", "data/scout.sqlite"), help="SQLite dataset path")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mempool-scout", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="stream mempool + blocks from a WebSocket node into SQLite")
    _add_params(c)
    c.add_argument("--wss", default=os.environ.get("SCOUT_WSS_URL"), help="WebSocket URL (or env SCOUT_WSS_URL)")
    c.add_argument("--vantage", default=os.environ.get("SCOUT_VANTAGE", "default"),
                   help="label for this collector location / provider")
    c.add_argument("--fetch-mode", choices=["full", "hash"], default="full",
                   help="'hash' only timestamps hashes (cheapest); 'full' also fetches and decodes txs")
    c.add_argument("--full-pending-objects", action="store_true",
                   help="ask the node to push full tx objects (geth-compatible nodes)")
    c.add_argument("--workers", type=int, default=32)
    c.add_argument("--queue-size", type=int, default=20_000)
    c.add_argument("--large-swap-eth", type=float, default=10.0)
    c.add_argument("--no-receipts", action="store_true", help="skip receipts (disables sandwich detection)")
    c.add_argument("--mempool-only", action="store_true",
                   help="only record pending sightings (an extra vantage point; another collector ingests blocks)")
    c.add_argument("--no-quotes", action="store_true", help="do not quote public swaps (no slippage data)")
    c.add_argument("--router", action="append", default=[], metavar="ADDRESS=LABEL",
                   help="extra router to decode, e.g. 0xabc...=my-fork (repeatable)")

    s = sub.add_parser("serve", help="run the REST API and dashboard")
    _add_params(s)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--large-swap-eth", type=float, default=10.0)

    st = sub.add_parser("status", help="print collection status per vantage point")
    _add_params(st)

    bk = sub.add_parser("backup", help="consistent online copy of the database (safe while collectors run)")
    _add_params(bk)
    bk.add_argument("--out", required=True, help="destination file, e.g. /data/backup-2026-11-04.sqlite")

    ls = sub.add_parser("label-sample", help="export a random sample of detected sandwiches for manual labelling")
    _add_params(ls)
    ls.add_argument("--n", type=int, default=100)
    ls.add_argument("--seed", type=int, default=1)
    ls.add_argument("--out", default="labels.csv")

    va = sub.add_parser("validate", help="detector precision from a labelled CSV (label column: TP or FP)")
    va.add_argument("labels", help="CSV produced by label-sample, with the label column filled in")

    r = sub.add_parser("report", help="write a Markdown + JSON research report")
    _add_params(r)
    r.add_argument("--out", default="reports")
    r.add_argument("--warmup-min", type=float, default=5.0)
    r.add_argument("--grace-ms", type=int, default=0)
    r.add_argument("--large-swap-eth", type=float, default=10.0)
    r.add_argument("--labels", help="labelled CSV to include detector precision in the report")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.cmd == "collect":
        if not args.wss:
            parser.error("a WebSocket URL is required: --wss or SCOUT_WSS_URL")
        from .collector import CollectorConfig, run_collector

        routers = dict(KNOWN_ROUTERS)
        for item in args.router:
            addr, _, label = item.partition("=")
            routers[addr.lower()] = label or "custom-router"
        run_collector(CollectorConfig(
            wss_url=args.wss, db_path=args.db, vantage=args.vantage, fetch_mode=args.fetch_mode,
            full_pending_objects=args.full_pending_objects, workers=args.workers, queue_size=args.queue_size,
            large_swap_eth=args.large_swap_eth, receipts=not args.no_receipts, routers=routers,
            blocks=not args.mempool_only, quotes=not args.no_quotes,
        ))
    elif args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(args.db, large_swap_eth=args.large_swap_eth), host=args.host, port=args.port)
    elif args.cmd == "report":
        from .report import write_report

        path = write_report(args.db, args.out, Params(int(args.warmup_min * 60_000), args.grace_ms),
                            args.large_swap_eth, labels=args.labels)
        print(f"report written to {path}")
    elif args.cmd == "status":
        _status(args.db)
    elif args.cmd == "backup":
        import sqlite3

        src = sqlite3.connect(args.db, timeout=60)
        dst = sqlite3.connect(args.out)
        with dst:
            src.backup(dst, pages=4096)
        dst.close()
        src.close()
        print(f"backup written to {args.out}")
    elif args.cmd == "label-sample":
        from . import analysis as A
        from .storage import connect

        conn = connect(args.db)
        rows = A.label_sample(conn, args.n, args.seed)
        A.write_label_csv(rows, args.out)
        print(f"wrote {len(rows)} sandwiches to {args.out}; open each URL and set label to TP or FP")
    elif args.cmd == "validate":
        from .analysis import precision_from_labels

        r = precision_from_labels(args.labels)
        ci = "n/a" if not r["ci95"] else f"{r['ci95'][0] * 100:.1f}–{r['ci95'][1] * 100:.1f}%"
        prec = "n/a" if r["precision"] is None else f"{r['precision'] * 100:.1f}%"
        print(f"precision {prec} (95% CI {ci})  TP={r['true_positives']} FP={r['false_positives']} "
              f"unlabelled={r['unlabelled']}")
    return 0


def _status(db: str) -> None:
    import time
    from pathlib import Path

    from . import analysis as A
    from .storage import connect

    conn = connect(db)
    now = time.time() * 1000
    head = conn.execute("SELECT MAX(number), MAX(received_ms), COUNT(*) FROM blocks").fetchone()
    size = sum(f.stat().st_size for f in Path(db).parent.glob(Path(db).name + "*")) / 1e9
    print(f"database   {db}  ({size:.2f} GB)")
    print(f"blocks     {head[2]:,} stored, head {head[0]}, last received "
          f"{'never' if not head[1] else f'{(now - head[1]) / 1000:.0f}s ago'}")
    for v in A.vantage_status(conn):
        age = (now - v["last_heartbeat_ms"]) / 1000 if v["last_heartbeat_ms"] else None
        state = "ACTIVE" if age is not None and age < 60 else "stopped"
        print(f"vantage    {v['vantage']:<20} {state:<8} {v['runtime_hours']:.1f} h over {v['sessions']} sessions, "
              f"endpoints: {v['endpoints']}")


if __name__ == "__main__":
    sys.exit(main())
