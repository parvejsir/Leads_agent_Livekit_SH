# Deprecated — agent logic has moved to app/agents/worker_agent/
# Kept as a thin re-export for backwards compatibility.
from app.agents.worker_agent.agent import RealEstateAgent

__all__ = ["RealEstateAgent"]
