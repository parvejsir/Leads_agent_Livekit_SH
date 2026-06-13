import threading
import uuid

from fastapi import APIRouter, HTTPException

from app.schemas.call_schema import StartCallRequest, StartCallResponse
from app.schemas.queue_schema import CallJob
from app.services.livekit_service import delete_room
from app.services.queue_manager import QUEUE_MANAGER
from app.core.logging import LOGGER

ROUTER = APIRouter(prefix="/call", tags=["call"])

# In-memory room registry: call_id → {room_name, phone}. Used by /call/end to
# tear down the right room. Touched from both the FastAPI loop (start/end) and
# the LiveKit worker thread (shutdown), so guard it with a threading.Lock.
ACTIVE_CALLS: dict[str, dict] = {}
_active_lock = threading.Lock()


def register_active_call(call_id: str, room_name: str, phone: str) -> None:
    with _active_lock:
        ACTIVE_CALLS[call_id] = {"room_name": room_name, "phone": phone}


def unregister_active_call(call_id: str) -> dict | None:
    with _active_lock:
        return ACTIVE_CALLS.pop(call_id, None)


def get_active_call(call_id: str) -> dict | None:
    with _active_lock:
        return ACTIVE_CALLS.get(call_id)


@ROUTER.post("/start", response_model=StartCallResponse)
async def start_call(body: StartCallRequest) -> StartCallResponse:
    """Single-number dial. Routes through the queue (queue of size 1) so slot
    accounting stays correct; with a free slot it dispatches immediately and the
    assigned call_id is returned — identical behavior to the old single call."""
    job = CallJob(id=uuid.uuid4().hex[:12], phone=body.phone_number)
    LOGGER.info(f"[{job.id}] Starting single call to {body.phone_number}")
    try:
        await QUEUE_MANAGER.enqueue([job])
    except Exception as e:
        LOGGER.error(f"[{job.id}] Failed to start call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Dispatched immediately when a slot was free; otherwise it's queued.
    if job.call_id:
        return StartCallResponse(
            call_id=job.call_id,
            room_name=f"room-{job.call_id}",
            status="dispatched",
        )
    return StartCallResponse(call_id="", room_name="", status="queued")


@ROUTER.post("/end/{call_id}")
async def end_call_route(call_id: str) -> dict:
    info = get_active_call(call_id)
    if not info:
        # Idempotent: the call may have already ended via hangup/disconnect.
        # Never error the frontend's End button on a harmless race.
        return {"status": "already_ended", "call_id": call_id}
    try:
        # Deleting the room disconnects all participants, including the SIP leg.
        # This triggers the agent's shutdown callback, which broadcasts call_ended.
        await delete_room(info["room_name"])
        unregister_active_call(call_id)
        return {"status": "ended", "call_id": call_id}
    except Exception as e:
        unregister_active_call(call_id)
        raise HTTPException(status_code=500, detail=str(e))


@ROUTER.get("/active")
async def list_active_calls() -> dict:
    with _active_lock:
        keys = list(ACTIVE_CALLS.keys())
    return {"calls": keys, "count": len(keys)}
