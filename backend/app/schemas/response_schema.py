from typing import Any, Literal, Optional
from pydantic import BaseModel
from app.schemas.lead_schema import LeadData


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    role: Literal["user", "agent"]
    text: str
    is_final: bool = True
    call_id: str


class LeadUpdateEvent(BaseModel):
    type: Literal["lead_update"] = "lead_update"
    call_id: str
    data: LeadData


class AgentStateEvent(BaseModel):
    type: Literal["agent_state"] = "agent_state"
    call_id: str
    state: Literal["idle", "listening", "thinking", "speaking"]


class CallConnectedEvent(BaseModel):
    type: Literal["call_connected"] = "call_connected"
    call_id: str


class HotLeadEvent(BaseModel):
    type: Literal["hot_lead_flagged"] = "hot_lead_flagged"
    call_id: str
    reason: str


class CallTransferredEvent(BaseModel):
    type: Literal["call_transferred"] = "call_transferred"
    call_id: str
    reason: str


class CallEndedEvent(BaseModel):
    type: Literal["call_ended"] = "call_ended"
    call_id: str
    duration_seconds: int
    lead_data: Optional[LeadData] = None
