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
    c.add_argument("--router", action="append", default=[], metavar="ADDRESS=LABEL",
                   help="extra router to decode, e.g. 0xabc...=my-fork (repeatable)")

    s = sub.add_parser("serve", help="run the REST API and dashboard")
    _add_params(s)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--large-swap-eth", type=float, default=10.0)

    r = sub.add_parser("report", help="write a Markdown + JSON research report")
    _add_params(r)
    r.add_argument("--out", default="reports")
    r.add_argument("--warmup-min", type=float, default=5.0)
    r.add_argument("--grace-ms", type=int, default=0)
    r.add_argument("--large-swap-eth", type=float, default=10.0)

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
        ))
    elif args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(args.db, large_swap_eth=args.large_swap_eth), host=args.host, port=args.port)
    elif args.cmd == "report":
        from .report import write_report

        path = write_report(args.db, args.out, Params(int(args.warmup_min * 60_000), args.grace_ms),
                            args.large_swap_eth)
        print(f"report written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
