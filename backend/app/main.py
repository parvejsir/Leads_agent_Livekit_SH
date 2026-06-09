"""
FastAPI application entry point.

Routes:
  GET  /                    — health check
  GET  /health              — health check
  POST /call/start          — dispatch agent + place outbound SIP call
  POST /call/end/{id}       — end a call (deletes LiveKit room)
  GET  /call/active         — list active calls
  WS   /ws/{call_id}        — frontend real-time events
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.call import ROUTER as CALL_ROUTER
from app.api.health import ROUTER as HEALTH_ROUTER
from app.api.history import ROUTER as HISTORY_ROUTER
from app.core.logging import LOGGER
from app.websocket.connection_manager import CONNECTION_MANAGER


# ── Lifespan: start LiveKit worker ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    CONNECTION_MANAGER.set_loop(loop)

    LOGGER.info("Starting LiveKit agent worker...")
    worker_task = None
    try:
        from app.agents.worker import create_agent_server
        server = create_agent_server()
        worker_task = asyncio.create_task(server.run(), name="livekit-worker")
        LOGGER.info("LiveKit agent worker running")
    except Exception as e:
        LOGGER.error(f"Failed to start LiveKit worker: {e}")

    yield

    if worker_task and not worker_task.done():
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass
    LOGGER.info("Shutdown complete")


# ── FastAPI app ───────────────────────────────────────────────────────────────

APP = FastAPI(title="HomePro Realty Voice AI", lifespan=lifespan)

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

APP.include_router(HEALTH_ROUTER)
APP.include_router(CALL_ROUTER)
APP.include_router(HISTORY_ROUTER)


@APP.get("/")
async def root():
    return {"message": "HomePro Realty Voice AI — server running", "status": "ok"}


# ── Frontend WebSocket (/ws/{call_id}) ────────────────────────────────────────

@APP.websocket("/ws/{call_id}")
async def frontend_ws(websocket: WebSocket, call_id: str):
    await CONNECTION_MANAGER.connect(call_id, websocket)
    LOGGER.info(f"[{call_id}] Frontend WS connected")
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        LOGGER.info(f"[{call_id}] Frontend WS disconnected")
    except Exception as e:
        LOGGER.debug(f"[{call_id}] Frontend WS error: {e}")
    finally:
        CONNECTION_MANAGER.disconnect(call_id, websocket)
