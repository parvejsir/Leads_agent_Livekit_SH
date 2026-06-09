import uuid
from datetime import datetime


def generate_call_id() -> str:
    return uuid.uuid4().hex[:12]


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
