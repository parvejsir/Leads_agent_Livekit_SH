from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.utils.helpers import utc_now_iso

# Queue job lifecycle. `pending` waits for a slot; `dialing` is being placed;
# `active` is a live conversation; the rest are terminal outcomes.
JobStatus = Literal[
    "pending",
    "dialing",
    "active",
    "completed",
    "failed",
    "busy",
    "no_answer",
    "voicemail",
]

TERMINAL_STATUSES: set[str] = {
    "completed",
    "failed",
    "busy",
    "no_answer",
    "voicemail",
}


class CallJob(BaseModel):
    """One queued outbound call. Persisted to storage/queue.json."""

    id: str
    phone: str
    name: Optional[str] = None
    # Customer's CURRENT location (from the uploaded file). This is NOT the
    # preferred property location discovered during the call (that lives in
    # LeadData.location). The two are kept strictly separate.
    contact_location: Optional[str] = None
    contact_id: Optional[str] = None
    batch_id: Optional[str] = None

    status: JobStatus = "pending"
    attempts: int = 0
    call_id: Optional[str] = None
    error: Optional[str] = None

    created_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
