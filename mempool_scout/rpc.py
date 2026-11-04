"""Minimal JSON-RPC-over-WebSocket client for Ethereum nodes.

Why not web3.py's WebSocketProvider?  During testing against public endpoints it
(1) sent ``["newPendingTransactions", false]``, which some nodes accept but never
deliver notifications for, and (2) hit the 1 MiB default frame limit on block
receipts.  This client is small, sends exactly the params given, supports large
frames, and routes subscription notifications to per-subscription queues.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

import websockets

from .utils import to_bytes

log = logging.getLogger("mempool_scout.rpc")


class RpcError(Exception):
    def __init__(self, error: Any):
        self.error = error
        super().__init__(error.get("message", str(error)) if isinstance(error, dict) else str(error))


class ConnectionClosed(Exception):
    pass


class WsRpcClient:
    def __init__(self, url: str, max_frame_bytes: int = 256 * 1024 * 1024, request_timeout: float = 30.0,
                 subscription_buffer: int = 200_000):
        self.url = url
        self.max_frame_bytes = max_frame_bytes
        self.request_timeout = request_timeout
        self.subscription_buffer = subscription_buffer
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subs: dict[str, asyncio.Queue] = {}
        self.dropped_notifications = 0
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self.closed = asyncio.Event()

    async def __aenter__(self) -> "WsRpcClient":
        self._ws = await websockets.connect(self.url, max_size=self.max_frame_bytes, open_timeout=20,
                                            ping_interval=20, ping_timeout=60, close_timeout=5)
        self._reader = asyncio.create_task(self._read_loop())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()
        self._fail_all(ConnectionClosed("client closed"))

    def _fail_all(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        for q in self._subs.values():
            try:
                q.put_nowait(None)  # sentinel: stream ended
            except asyncio.QueueFull:
                pass
        self.closed.set()

    def _queue(self, sub_id: str) -> asyncio.Queue:
        q = self._subs.get(sub_id)
        if q is None:
            q = self._subs[sub_id] = asyncio.Queue(maxsize=self.subscription_buffer)
        return q

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                for m in msg if isinstance(msg, list) else [msg]:
                    if m.get("method") == "eth_subscription":
                        params = m.get("params") or {}
                        try:
                            self._queue(params.get("subscription")).put_nowait(params.get("result"))
                        except asyncio.QueueFull:
                            self.dropped_notifications += 1
                    elif "id" in m:
                        fut = self._pending.pop(m["id"], None)
                        if fut is not None and not fut.done():
                            fut.set_result(m)
            self._fail_all(ConnectionClosed("server closed the connection"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("reader stopped: %s", e)
            self._fail_all(ConnectionClosed(str(e)))

    async def request(self, method: str, params: list[Any] | None = None) -> Any:
        if self.closed.is_set():
            raise ConnectionClosed("connection is closed")
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or []}))
        try:
            resp = await asyncio.wait_for(fut, self.request_timeout)
        finally:
            self._pending.pop(req_id, None)
        if "error" in resp:
            raise RpcError(resp["error"])
        return resp.get("result")

    async def subscribe(self, *params: Any) -> tuple[str, asyncio.Queue]:
        sub_id = await self.request("eth_subscribe", list(params))
        return sub_id, self._queue(sub_id)


class EthRpc:
    """The handful of ``eth_*`` calls the collector needs, returning raw JSON."""

    def __init__(self, client: WsRpcClient):
        self.client = client

    async def chain_id(self) -> int:
        return int(await self.client.request("eth_chainId"), 16)

    async def block_number(self) -> int:
        return int(await self.client.request("eth_blockNumber"), 16)

    async def get_block(self, number: int, full_transactions: bool = True) -> dict[str, Any] | None:
        return await self.client.request("eth_getBlockByNumber", [hex(number), full_transactions])

    async def get_block_receipts(self, number: int) -> list[dict[str, Any]] | None:
        return await self.client.request("eth_getBlockReceipts", [hex(number)])

    async def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        return await self.client.request("eth_getTransactionByHash", [tx_hash])

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return await self.client.request("eth_getTransactionReceipt", [tx_hash])

    async def call(self, tx: dict[str, Any]) -> bytes:
        return to_bytes(await self.client.request("eth_call", [tx, "latest"]))
