from fastapi import APIRouter, HTTPException

from app.services.storage_service import list_call_history, get_call_history

ROUTER = APIRouter(prefix="/calls", tags=["history"])


@ROUTER.get("")
async def list_calls() -> dict:
    """All completed calls, newest first (lightweight — no transcript)."""
    calls = await list_call_history()
    return {"calls": calls, "count": len(calls)}


@ROUTER.get("/{call_id}")
async def get_call(call_id: str) -> dict:
    """Full record for a single call, including transcript and lead data."""
    record = await get_call_history(call_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call not found")
    return record
