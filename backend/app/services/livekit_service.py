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


async def create_room(call_id: str, phone: str = "") -> str:
    room_name = f"{ROOM_PREFIX}-{call_id}"
    client = _make_client()
    try:
        await client.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=json.dumps({"call_id": call_id, "phone": phone}),
                empty_timeout=300,   # auto-delete after 5min empty
                max_participants=10,
            )
        )
    finally:
        await client.aclose()
    return room_name


async def dispatch_agent(room_name: str, call_id: str, phone_number: str) -> str:
    """Dispatch the real estate agent to the room so it's ready when audio arrives."""
    client = _make_client()
    try:
        dispatch = await client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=f'{{"call_id": "{call_id}", "phone": "{phone_number}"}}',
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
