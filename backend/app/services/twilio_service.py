from twilio.rest import Client

from app.core.config import SETTINGS

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(SETTINGS.TWILIO_ACCOUNT_SID, SETTINGS.TWILIO_AUTH_TOKEN)
    return _client


def end_call(call_sid: str) -> None:
    _get_client().calls(call_sid).update(status="completed")


def transfer_call_to_human(call_sid: str, human_number: str) -> None:
    """Perform a warm transfer to a human agent number."""
    twiml = (
        "<Response>"
        "<Say>Please hold while I connect you to our senior consultant.</Say>"
        f"<Dial>{human_number}</Dial>"
        "</Response>"
    )
    _get_client().calls(call_sid).update(twiml=twiml)
