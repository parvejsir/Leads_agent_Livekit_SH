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
    - The conversation requires legal or financial expertise beyond your scope
    This will connect the customer to a senior consultant.
    """
    call_id: str = context.userdata.get("call_id", "")
    LOGGER.info(f"[{call_id}] TRANSFER requested: {reason}")
    CONNECTION_MANAGER.broadcast_from_thread(
        call_id,
        {"type": "call_transferred", "call_id": call_id, "reason": reason},
    )
    return "Connecting you to our senior consultant now. Please hold for a moment."


@function_tool
async def update_lead_fields(
    context: RunContext,
    name: Annotated[str | None, "Customer's name if mentioned"] = None,
    location: Annotated[str | None, "Desired city or area"] = None,
    budget_min: Annotated[int | None, "Minimum budget in lakhs INR"] = None,
    budget_max: Annotated[int | None, "Maximum budget in lakhs INR"] = None,
    bhk: Annotated[int | None, "BHK preference: 1, 2, 3, 4, or 5"] = None,
    property_type: Annotated[
        str | None, "One of: apartment, villa, plot, commercial"
    ] = None,
    ready_to_move: Annotated[
        bool | None, "True if customer wants ready-to-move, False for under-construction"
    ] = None,
    interest_level: Annotated[
        str | None, "One of: cold, warm, hot"
    ] = None,
    purpose: Annotated[
        str | None, "One of: self_use, investment, rental"
    ] = None,
) -> str:
    """
    Call this silently whenever the customer reveals any of their requirements during conversation.
    Use this to keep the lead record updated in real time.
    You can call this multiple times as you learn more about the customer.
    """
    call_id: str = context.userdata.get("call_id", "")

    if "lead_data" not in context.userdata:
        context.userdata["lead_data"] = {}

    lead = context.userdata["lead_data"]
    updates: dict = {}
    if name is not None:
        lead["name"] = name
        updates["name"] = name
    if location is not None:
        lead["location"] = location
        updates["location"] = location
    if budget_min is not None:
        lead["budget_min"] = budget_min
        updates["budget_min"] = budget_min
    if budget_max is not None:
        lead["budget_max"] = budget_max
        updates["budget_max"] = budget_max
    if bhk is not None:
        lead["bhk"] = bhk
        updates["bhk"] = bhk
    if property_type is not None:
        lead["property_type"] = property_type
        updates["property_type"] = property_type
    if ready_to_move is not None:
        lead["ready_to_move"] = ready_to_move
        updates["ready_to_move"] = ready_to_move
    if interest_level is not None:
        lead["interest_level"] = interest_level
        updates["interest_level"] = interest_level
    if purpose is not None:
        lead["purpose"] = purpose
        updates["purpose"] = purpose

    if updates:
        CONNECTION_MANAGER.broadcast_from_thread(
            call_id,
            {"type": "lead_update", "call_id": call_id, "data": lead},
        )

    return "Lead fields updated."
