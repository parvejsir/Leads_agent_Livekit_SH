"""
LLM-callable function tools for the real estate agent.
The agent decides when to call these based on conversation context.
"""

from typing import Annotated
from livekit.agents import function_tool, RunContext

from app.core.logging import LOGGER
from app.websocket.connection_manager import CONNECTION_MANAGER


@function_tool
async def flag_hot_lead(
    context: RunContext,
    reason: Annotated[str, "Why this lead is considered hot — their stated intent"],
) -> str:
    """
    Call this when the customer shows clear buying intent:
    - Has given location + budget + BHK preferences
    - Wants to schedule a site visit
    - Asking about payment plans, EMI, or booking procedure
    - Says they want to buy soon (within 3 months)
    Use this to alert the sales team for immediate follow-up.
    """
    call_id: str = context.userdata.get("call_id", "")
    LOGGER.info(f"[{call_id}] HOT LEAD flagged: {reason}")
    CONNECTION_MANAGER.broadcast_from_thread(
        call_id,
        {"type": "hot_lead_flagged", "call_id": call_id, "reason": reason},
    )
    if "lead_data" in context.userdata:
        context.userdata["lead_data"]["interest_level"] = "hot"
        context.userdata["lead_data"]["is_interested"] = True
    return "The lead has been flagged as high priority. Our team will follow up within 2 hours."


@function_tool
async def transfer_call(
    context: RunContext,
    reason: Annotated[str, "Why transfer is needed — e.g. 'customer wants site visit'"],
) -> str:
    """
    Call this when:
    - The customer explicitly asks to speak with a human consultant
    - The customer wants to book a site visit and needs confirmation
    - The customer says they are interested and wants property/location details
    - The conversation requires legal or financial expertise beyond your scope
    This connects the customer to a senior consultant. After you say the handoff
    line, the call ends (a real specialist transfer will be wired in later).
    """
    call_id: str = context.userdata.get("call_id", "")
    LOGGER.info(f"[{call_id}] TRANSFER requested: {reason}")
    CONNECTION_MANAGER.broadcast_from_thread(
        call_id,
        {"type": "call_transferred", "call_id": call_id, "reason": reason},
    )
    # Signal the worker to hang up once the closing line below has been spoken.
    context.userdata["pending_hangup"] = True
    return "Connecting you to our senior consultant now. Please hold for a moment."
