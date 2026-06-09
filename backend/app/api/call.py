from fastapi import APIRouter, HTTPException

from app.schemas.call_schema import StartCallRequest, StartCallResponse
from app.services.livekit_service import create_room, delete_room, dispatch_agent
from app.utils.helpers import generate_call_id
from app.core.logging import LOGGER

ROUTER = APIRouter(prefix="/call", tags=["call"])

# In-memory call registry: call_id → {room_name, phone}
ACTIVE_CALLS: dict[str, dict] = {}


@ROUTER.post("/start", response_model=StartCallResponse)
async def start_call(body: StartCallRequest) -> StartCallResponse:
    call_id = generate_call_id()
    LOGGER.info(f"[{call_id}] Starting call to {body.phone_number}")

    try:
        # 1. Create LiveKit room
        room_name = await create_room(call_id, body.phone_number)
        LOGGER.info(f"[{call_id}] Room created: {room_name}")

        # 2. Dispatch agent — agent places the SIP call inside its entrypoint
        await dispatch_agent(room_name, call_id, body.phone_number)
        LOGGER.info(f"[{call_id}] Agent dispatched — will place SIP call on answer")

        ACTIVE_CALLS[call_id] = {"room_name": room_name, "phone": body.phone_number}

        return StartCallResponse(call_id=call_id, room_name=room_name)

    except Exception as e:
        LOGGER.error(f"[{call_id}] Failed to start call: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@ROUTER.post("/end/{call_id}")
async def end_call_route(call_id: str) -> dict:
    info = ACTIVE_CALLS.get(call_id)
    if not info:
        # Idempotent: the call may have already ended via hangup/disconnect.
        # Never error the frontend's End button on a harmless race.
        return {"status": "already_ended", "call_id": call_id}
    try:
        # Deleting the room disconnects all participants, including the SIP leg.
        # This triggers the agent's shutdown callback, which broadcasts call_ended.
        await delete_room(info["room_name"])
        ACTIVE_CALLS.pop(call_id, None)
        return {"status": "ended", "call_id": call_id}
    except Exception as e:
        ACTIVE_CALLS.pop(call_id, None)
        raise HTTPException(status_code=500, detail=str(e))


@ROUTER.get("/active")
async def list_active_calls() -> dict:
    return {"calls": list(ACTIVE_CALLS.keys()), "count": len(ACTIVE_CALLS)}
