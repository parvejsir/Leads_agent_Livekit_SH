import asyncio
from collections import defaultdict
from typing import DefaultDict
from fastapi import WebSocket


class ConnectionManager:
    """
    In-process WebSocket pub/sub for broadcasting call events to frontend clients.
    Supports both async (FastAPI handlers) and threaded (LiveKit worker) callers.
    """

    def __init__(self):
        self._connections: DefaultDict[str, list[WebSocket]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, call_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[call_id].append(ws)

    def disconnect(self, call_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(call_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns and call_id in self._connections:
            del self._connections[call_id]

    async def broadcast(self, call_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(call_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(call_id, ws)

    def broadcast_from_thread(self, call_id: str, message: dict) -> None:
        """Called from LiveKit worker thread — schedules broadcast on the main event loop."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self.broadcast(call_id, message),
                self._loop,
            )


CONNECTION_MANAGER = ConnectionManager()
