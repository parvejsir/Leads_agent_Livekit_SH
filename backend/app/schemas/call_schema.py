from pydantic import BaseModel


class StartCallRequest(BaseModel):
    phone_number: str


class StartCallResponse(BaseModel):
    call_id: str
    room_name: str
    call_sid: str = ""
    status: str = "dispatched"
