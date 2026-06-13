from typing import AsyncIterable

from livekit.agents import Agent, ModelSettings

from app.agents.worker_agent.prompts import SYSTEM_PROMPT
from app.agents.worker_agent.tools import flag_hot_lead, transfer_call
from app.websocket.connection_manager import CONNECTION_MANAGER


class RealEstateAgent(Agent):
    """Arjun — HomePro Realty's outbound voice sales agent."""

    def __init__(self):
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[flag_hot_lead, transfer_call],
        )

    def transcription_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ):
        """Stream the agent's spoken text to the UI as it's generated, the same
        way user STT streams — instead of one bubble after the agent stops.

        We wrap the incoming text stream so each chunk is broadcast (cumulative,
        is_final=False) and a final is sent at the end, while still yielding every
        chunk through the default node so TTS/forwarding stays intact."""
        call_id = None
        try:
            call_id = self.session.userdata.get("call_id")
        except Exception:
            call_id = None

        async def _tap() -> AsyncIterable[str]:
            buffer = ""
            async for chunk in text:
                buffer += str(chunk)
                if call_id and buffer.strip():
                    CONNECTION_MANAGER.broadcast_from_thread(call_id, {
                        "type":     "transcript",
                        "role":     "agent",
                        "text":     buffer.strip(),
                        "is_final": False,
                        "call_id":  call_id,
                    })
                yield chunk
            if call_id and buffer.strip():
                CONNECTION_MANAGER.broadcast_from_thread(call_id, {
                    "type":     "transcript",
                    "role":     "agent",
                    "text":     buffer.strip(),
                    "is_final": True,
                    "call_id":  call_id,
                })

        return Agent.default.transcription_node(self, _tap(), model_settings)
