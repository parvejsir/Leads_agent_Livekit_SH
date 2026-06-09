from typing import Literal, Optional
from pydantic import BaseModel


class LeadData(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    budget_min: Optional[int] = None        # in lakhs INR
    budget_max: Optional[int] = None
    property_type: Optional[Literal["apartment", "villa", "plot", "commercial"]] = None
    bhk: Optional[int] = None              # 1 / 2 / 3 / 4 / 5
    ready_to_move: Optional[bool] = None
    purpose: Optional[Literal["self_use", "investment", "rental"]] = None
    interest_level: Optional[Literal["cold", "warm", "hot"]] = None
    is_interested: Optional[bool] = None
    notes: Optional[str] = None
