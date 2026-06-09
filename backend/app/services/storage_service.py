import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.schemas.lead_schema import LeadData

STORAGE_DIR = Path(__file__).parent.parent.parent / "storage"
DB_FILE = STORAGE_DIR / "db.txt"
LEADS_FILE = STORAGE_DIR / "leads.json"
CALLS_FILE = STORAGE_DIR / "calls.json"

_leads_lock = asyncio.Lock()
_calls_lock = asyncio.Lock()


def _ensure_storage():
    STORAGE_DIR.mkdir(exist_ok=True)
    if not DB_FILE.exists():
        DB_FILE.touch()
    if not LEADS_FILE.exists():
        LEADS_FILE.write_text("[]", encoding="utf-8")
    if not CALLS_FILE.exists():
        CALLS_FILE.write_text("[]", encoding="utf-8")


async def save_call_record(
    call_id: str,
    phone: str,
    transcript: list[dict],
    duration_s: int,
    lead_data: Optional[LeadData] = None,
) -> None:
    def _write():
        _ensure_storage()
        ts = datetime.utcnow().isoformat()
        lines = [
            f"\n{'='*60}",
            f"CALL ID  : {call_id}",
            f"TIMESTAMP: {ts}",
            f"PHONE    : {phone}",
            f"DURATION : {duration_s}s",
            f"TURNS    : {len(transcript)}",
        ]
        if lead_data:
            lines.append(f"LEAD     : {lead_data.model_dump(exclude_none=True)}")
        lines.append("TRANSCRIPT:")
        for turn in transcript:
            role = turn.get("role", "?").upper()
            text = turn.get("text", "")
            lines.append(f"  [{role}]: {text}")
        lines.append("=" * 60)
        with open(DB_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    await asyncio.to_thread(_write)


async def upsert_lead(
    call_id: str,
    phone: str,
    lead_data: LeadData,
    duration_s: int = 0,
) -> None:
    async with _leads_lock:
        def _write():
            _ensure_storage()
            leads: list[dict] = []
            try:
                content = LEADS_FILE.read_text(encoding="utf-8").strip()
                if content:
                    leads = json.loads(content)
            except (json.JSONDecodeError, FileNotFoundError):
                leads = []

            leads = [l for l in leads if l.get("call_id") != call_id]
            leads.append(
                {
                    "call_id": call_id,
                    "phone": phone,
                    "timestamp": datetime.utcnow().isoformat(),
                    "duration_seconds": duration_s,
                    **lead_data.model_dump(exclude_none=True),
                }
            )
            LEADS_FILE.write_text(
                json.dumps(leads, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)


def _read_calls_sync() -> list[dict]:
    _ensure_storage()
    try:
        content = CALLS_FILE.read_text(encoding="utf-8").strip()
        return json.loads(content) if content else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


async def save_call_history(record: dict) -> None:
    """Upsert a structured per-call record into calls.json (keyed by call_id)."""
    async with _calls_lock:
        def _write():
            calls = _read_calls_sync()
            calls = [c for c in calls if c.get("call_id") != record.get("call_id")]
            calls.append(record)
            # Atomic-ish write: temp file then replace.
            tmp = CALLS_FILE.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(calls, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(CALLS_FILE)

        await asyncio.to_thread(_write)


async def list_call_history() -> list[dict]:
    """All call records, newest first, as lightweight summaries (no transcript)."""
    def _read():
        calls = _read_calls_sync()
        calls.sort(key=lambda c: c.get("start_time") or "", reverse=True)
        summaries = []
        for c in calls:
            summaries.append({
                "call_id":          c.get("call_id"),
                "phone":            c.get("phone"),
                "start_time":       c.get("start_time"),
                "end_time":         c.get("end_time"),
                "duration_seconds": c.get("duration_seconds", 0),
                "status":           c.get("status", "completed"),
                "summary":          c.get("summary", ""),
                "turns":            len(c.get("transcript") or []),
                "lead_data":        c.get("lead_data", {}),
            })
        return summaries

    return await asyncio.to_thread(_read)


async def get_call_history(call_id: str) -> Optional[dict]:
    """Full record for a single call, including transcript."""
    def _read():
        for c in _read_calls_sync():
            if c.get("call_id") == call_id:
                return c
        return None

    return await asyncio.to_thread(_read)
