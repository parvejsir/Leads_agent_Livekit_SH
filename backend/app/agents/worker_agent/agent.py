from livekit.agents import Agent

from app.agents.worker_agent.prompts import SYSTEM_PROMPT
from app.agents.worker_agent.tools import flag_hot_lead, transfer_call


class RealEstateAgent(Agent):
    """Arjun — HomePro Realty's outbound voice sales agent."""

    def __init__(self):
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[flag_hot_lead, transfer_call],
        )
