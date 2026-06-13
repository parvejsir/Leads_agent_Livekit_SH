import json

from livekit import api

from app.core.config import SETTINGS
from app.core.constants import AGENT_NAME, ROOM_PREFIX


def _make_client() -> api.LiveKitAPI:
    return api.LiveKitAPI(
        SETTINGS.LIVEKIT_URL,
        SETTINGS.LIVEKIT_API_KEY,
        SETTINGS.LIVEKIT_API_SECRET,
    )


def _call_metadata(
    call_id: str,
    phone: str,
    name: str | None,
    contact_location: str | None,
    contact_id: str | None,
) -> str:
    # contact_location is the customer's CURRENT location — never the preferred
    # property location (that is extracted from the conversation into LeadData).
    return json.dumps({
        "call_id": call_id,
        "phone": phone,
        "name": name,
        "contact_location": contact_location,
        "contact_id": contact_id,
    })


async def create_room(
    call_id: str,
    phone: str = "",
    name: str | None = None,
    contact_location: str | None = None,
    contact_id: str | None = None,
) -> str:
    room_name = f"{ROOM_PREFIX}-{call_id}"
    client = _make_client()
    try:
        await client.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=_call_metadata(call_id, phone, name, contact_location, contact_id),
                empty_timeout=300,   # auto-delete after 5min empty
                max_participants=10,
            )
        )
    finally:
        await client.aclose()
    return room_name


async def dispatch_agent(
    room_name: str,
    call_id: str,
    phone_number: str,
    name: str | None = None,
    contact_location: str | None = None,
    contact_id: str | None = None,
) -> str:
    """Dispatch the real estate agent to the room so it's ready when audio arrives."""
    client = _make_client()
    try:
        dispatch = await client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=_call_metadata(call_id, phone_number, name, contact_location, contact_id),
            )
        )
        return dispatch.id if dispatch else ""
    finally:
        await client.aclose()


async def delete_room(room_name: str) -> None:
    client = _make_client()
    try:
        await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
    finally:
        await client.aclose()


def create_token(room_name: str, identity: str) -> str:
    token = (
        api.AccessToken(SETTINGS.LIVEKIT_API_KEY, SETTINGS.LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )
    return token
