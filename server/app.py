"""Local attention server for the Anchor extension.

Run from this folder:
    python -m uvicorn app:app --host 127.0.0.1 --port 8765

The extension opens one WebSocket per session. Client -> server messages:
    {"type": "start", "config": {...}}   begin watching the camera
    {"type": "recalibrate"}              treat the current pose as "looking at the screen"
    {"type": "stop"}                     stop and release the camera
Server -> client messages: status / state / away / returned (see monitor.py) and
a periodic {"type": "ping"} that keeps the extension's service worker awake.

The camera is only open while a client is connected and has sent "start".
"""

from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from anchor_attention.config import MODEL_PATH, camera_source
from anchor_attention.monitor import AttentionMonitor
from anchor_attention.tracker import TrackerConfig

PING_SECONDS = 20


def _origin_allowed(origin: str | None) -> bool:
    """Any website can open a WebSocket to localhost, so only let the extension in.

    Browsers always send an Origin header. Set ANCHOR_ALLOWED_ORIGINS to a
    comma-separated list (e.g. chrome-extension://<your-extension-id>) to lock
    it to your install.
    """
    if origin is None:
        return True  # not a browser (e.g. tests, curl)
    allowed = [o.strip() for o in os.environ.get("ANCHOR_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if allowed:
        return origin in allowed
    return origin.startswith("chrome-extension://")


app = FastAPI(title="Anchor attention server")
_active_monitor: AttentionMonitor | None = None  # only one camera, so only one monitor


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "anchor-attention", "modelFound": MODEL_PATH.exists()}


async def _pump(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
        except asyncio.TimeoutError:
            event = {"type": "ping"}
        await websocket.send_json(event)


async def _stop_monitor(monitor: AttentionMonitor | None) -> None:
    global _active_monitor
    if monitor is None:
        return
    await asyncio.get_running_loop().run_in_executor(None, monitor.stop)
    if _active_monitor is monitor:
        _active_monitor = None


@app.websocket("/attention/ws")
async def attention_ws(websocket: WebSocket) -> None:
    global _active_monitor

    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:  # called from the monitor thread
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            pass  # loop already closed during shutdown

    pump = asyncio.create_task(_pump(websocket, queue))
    monitor: AttentionMonitor | None = None
    try:
        while True:
            try:
                message = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                continue
            kind = message.get("type") if isinstance(message, dict) else None

            if kind == "start":
                await _stop_monitor(_active_monitor)  # frees the camera from an earlier connection
                await _stop_monitor(monitor)
                try:
                    config = TrackerConfig.from_dict(message.get("config") or {})
                except (TypeError, ValueError):
                    emit({"type": "status", "status": "error", "error": "bad-config"})
                    continue
                monitor = AttentionMonitor(MODEL_PATH, camera_source(), emit)
                _active_monitor = monitor
                monitor.start(config)
            elif kind == "recalibrate" and monitor is not None:
                monitor.request_recalibrate()
            elif kind == "stop":
                await _stop_monitor(monitor)
                monitor = None
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        await _stop_monitor(monitor)
