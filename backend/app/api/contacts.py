"""
Contact intake → call queue.

  POST /contacts/import   — upload CSV/XLSX/XLS, parse, enqueue
  POST /contacts/enqueue  — manual comma-separated numbers, enqueue
  GET  /contacts/queue    — current queue snapshot (polling fallback for the UI)
"""

import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.logging import LOGGER
from app.schemas.queue_schema import CallJob
from app.services.contact_parser import UnsupportedFormatError, parse_contacts
from app.services.queue_manager import QUEUE_MANAGER

ROUTER = APIRouter(prefix="/contacts", tags=["contacts"])

_PHONE_RE = re.compile(r"^\+?\d{10,15}$")


class EnqueueRequest(BaseModel):
    # Either a single comma-separated string or a list of numbers.
    numbers: str | list[str]
    # Optional phone → name map for personalized greetings.
    names: dict[str, str] | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_phone(s: str) -> str:
    s = s.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    return ("+" + digits) if plus else digits


@ROUTER.post("/import")
async def import_contacts(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    try:
        result = parse_contacts(file.filename or "upload", raw)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        LOGGER.error(f"[contacts] parse failed: {e}")
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    batch_id = _new_id()
    jobs = [
        CallJob(
            id=_new_id(),
            phone=c.phone,
            name=c.name,
            contact_location=c.contact_location,
            contact_id=c.contact_id,
            batch_id=batch_id,
        )
        for c in result.contacts
    ]
    if jobs:
        await QUEUE_MANAGER.enqueue(jobs)

    return {
        "batch_id": batch_id,
        "accepted": len(jobs),
        "rejected": result.rejected,
    }


@ROUTER.post("/enqueue")
async def enqueue_numbers(body: EnqueueRequest) -> dict:
    if isinstance(body.numbers, str):
        raw_list = body.numbers.split(",")
    else:
        raw_list = body.numbers

    names = body.names or {}
    batch_id = _new_id()
    jobs: list[CallJob] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for raw in raw_list:
        phone = _normalize_phone(raw)
        if not phone or not _PHONE_RE.match(phone):
            rejected.append({"phone": raw.strip(), "reason": "invalid phone"})
            continue
        key = re.sub(r"\D", "", phone)  # dedupe ignoring +/formatting
        if key in seen:
            rejected.append({"phone": phone, "reason": "duplicate"})
            continue
        seen.add(key)
        jobs.append(
            CallJob(
                id=_new_id(),
                phone=phone,
                name=names.get(phone) or names.get(raw.strip()),
                batch_id=batch_id,
            )
        )

    if jobs:
        await QUEUE_MANAGER.enqueue(jobs)

    return {"batch_id": batch_id, "accepted": len(jobs), "rejected": rejected}


@ROUTER.get("/queue")
async def get_queue() -> dict:
    return QUEUE_MANAGER.snapshot()


@ROUTER.post("/queue/clear")
async def clear_finished() -> dict:
    removed = await QUEUE_MANAGER.clear_finished()
    return {"removed": removed}
