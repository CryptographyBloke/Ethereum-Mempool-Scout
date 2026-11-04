"""REST + Server-Sent-Events API for the dashboard.

Reads the SQLite file the collector writes.  Run with::

    mempool-scout serve --db data/scout.sqlite

and open http://127.0.0.1:8000.  If ``frontend/dist`` exists it is served at ``/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import analysis as A
from .decoders import supported_selectors
from .constants import KNOWN_ROUTERS
from .storage import connect

DEFAULT_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app(db_path: str, frontend_dir: str | Path | None = DEFAULT_FRONTEND,
               large_swap_eth: float = 10.0) -> FastAPI:
    connect(db_path).close()  # make sure the file and schema exist

    app = FastAPI(title="Ethereum Mempool Scout API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("SCOUT_CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @contextmanager
    def db() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path, readonly=True)
        try:
            yield conn
        finally:
            conn.close()

    def params(warmup_min: float, grace_ms: int) -> A.Params:
        return A.Params(warmup_ms=int(warmup_min * 60_000), grace_ms=grace_ms)

    W = Query(5.0, ge=0, le=240, description="Ignore blocks this many minutes after a session started")
    G = Query(0, ge=-12_000, le=12_000, description="Grace period after block timestamp, in ms")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with db() as c:
            last = c.execute("SELECT MAX(heartbeat_ms) FROM sessions").fetchone()[0]
            head = c.execute("SELECT MAX(number) FROM blocks").fetchone()[0]
        return {"version": __version__, "last_heartbeat_ms": last, "head": head}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {"routers": KNOWN_ROUTERS, "selectors": supported_selectors(), "large_swap_eth": large_swap_eth}

    @app.get("/api/overview")
    def overview(warmup_min: float = W, grace_ms: int = G) -> dict[str, Any]:
        with db() as c:
            return A.overview(c, params(warmup_min, grace_ms), large_swap_eth)

    @app.get("/api/visibility/timeseries")
    def timeseries(bucket_s: int = Query(3600, ge=60, le=86_400), warmup_min: float = W,
                   grace_ms: int = G) -> list[dict[str, Any]]:
        with db() as c:
            return A.visibility_timeseries(c, params(warmup_min, grace_ms), bucket_s)

    @app.get("/api/visibility/types")
    def by_type(warmup_min: float = W, grace_ms: int = G) -> list[dict[str, Any]]:
        with db() as c:
            return A.visibility_by_type(c, params(warmup_min, grace_ms))

    @app.get("/api/visibility/delay")
    def delay(warmup_min: float = W, grace_ms: int = G) -> dict[str, Any]:
        with db() as c:
            return A.inclusion_delay(c, params(warmup_min, grace_ms))

    @app.get("/api/builders")
    def builders(limit: int = Query(15, ge=1, le=100), warmup_min: float = W, grace_ms: int = G) -> list[dict[str, Any]]:
        with db() as c:
            return A.builders(c, params(warmup_min, grace_ms), limit)

    @app.get("/api/exposure")
    def exposure(warmup_min: float = W, grace_ms: int = G) -> dict[str, Any]:
        with db() as c:
            return A.exposure(c, params(warmup_min, grace_ms))

    @app.get("/api/blocks")
    def blocks(limit: int = Query(25, ge=1, le=200), before: int | None = None, grace_ms: int = G) -> list[dict[str, Any]]:
        with db() as c:
            return A.recent_blocks(c, params(0, grace_ms), limit, before)

    @app.get("/api/blocks/{number}")
    def block(number: int, grace_ms: int = G) -> dict[str, Any]:
        with db() as c:
            b = A.block_detail(c, number, params(0, grace_ms))
        if b is None:
            raise HTTPException(404, "block not in dataset")
        return b

    @app.get("/api/sandwiches")
    def sandwiches(limit: int = Query(50, ge=1, le=500), grace_ms: int = G) -> list[dict[str, Any]]:
        with db() as c:
            return A.sandwich_list(c, params(0, grace_ms), limit)

    @app.get("/api/swaps/large")
    def large(min_eth: float = Query(large_swap_eth, ge=0), limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        with db() as c:
            return A.large_swaps(c, min_eth, limit)

    @app.get("/api/tx/{tx_hash}")
    def tx(tx_hash: str) -> dict[str, Any]:
        if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
            raise HTTPException(400, "expected a 0x-prefixed 32-byte hash")
        with db() as c:
            r = A.tx_lookup(c, tx_hash)
        if r is None:
            raise HTTPException(404, "transaction not in dataset")
        return r

    @app.get("/api/alerts")
    def alerts(after_id: int = 0, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        with db() as c:
            return A.alerts_since(c, after_id, limit)

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        """Server-Sent Events: pushes new blocks and alerts as the collector writes them."""

        async def gen():
            with db() as c:
                last_block = c.execute("SELECT COALESCE(MAX(number), 0) FROM blocks").fetchone()[0]
                last_alert = c.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
            yield "retry: 3000\n\n"
            while True:
                await asyncio.sleep(1.0)
                with db() as c:
                    new_blocks = A.recent_blocks(c, A.Params(), limit=10)
                    new_blocks = [b for b in new_blocks if b["number"] > last_block]
                    new_alerts = A.alerts_since(c, last_alert, 50)
                for b in sorted(new_blocks, key=lambda b: b["number"]):
                    last_block = b["number"]
                    yield f"event: block\ndata: {json.dumps(b)}\n\n"
                for a in sorted(new_alerts, key=lambda a: a["id"]):
                    last_alert = a["id"]
                    yield f"event: alert\ndata: {json.dumps(a)}\n\n"
                yield ": keep-alive\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if frontend_dir and Path(frontend_dir, "index.html").exists():
        dist = Path(frontend_dir)
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    return app
