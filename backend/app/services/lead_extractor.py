import asyncio
import json
import time

from google import genai
from google.genai import types

from app.core.config import SETTINGS
from app.core.logging import LOGGER
from app.schemas.lead_schema import LeadData

_client: genai.Client | None = None

# Single prompt that extracts the structured lead AND a short summary in ONE
# Gemini call. Previously this was two separate calls (extract + summarize),
# doubling post-call request count against the free-tier RPM/RPD budget.
EXTRACTION_PROMPT = """
You are a lead data extractor for a real estate company.
Given a phone call transcript between an AI agent (Arjun) and a customer,
extract structured lead information as JSON. Only fill fields where the customer clearly stated information.
Return null for any field not mentioned or unclear.

Rules:
- Budget values must be in Indian Rupees in LAKHS (e.g. "50 lakhs" → 50, "1 crore" → 100)
- interest_level: "hot" = actively wants to buy / asked for site visit / pricing
                  "warm" = showed interest but not committed
                  "cold" = not interested or unresponsive
- is_interested: true if interest_level is "warm" or "hot"
- summary: a concise 1-2 sentence plain-text summary of what happened and the
           customer's interest (no markdown, no preamble). Empty string if there
           is nothing meaningful to summarize.

Return ONLY valid JSON matching this schema:
{
  "name": string or null,
  "location": string or null,
  "budget_min": integer or null,
  "budget_max": integer or null,
  "property_type": "apartment"|"villa"|"plot"|"commercial"|null,
  "bhk": integer or null,
  "ready_to_move": boolean or null,
  "purpose": "self_use"|"investment"|"rental"|null,
  "interest_level": "cold"|"warm"|"hot"|null,
  "is_interested": boolean or null,
  "notes": string or null,
  "summary": string
}
"""


def _is_quota_error(exc: Exception) -> bool:
    """True if the exception is a rate-limit / quota (429) error.

    Retrying on a 429 just fires more requests into an already-exhausted
    per-minute bucket and makes the quota problem strictly worse, so the caller
    bails immediately instead of looping.
    """
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg or "rate limit" in msg


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=SETTINGS.GEMINI_API_KEY)
    return _client


def _format_transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        role = "AGENT" if t.get("role") == "agent" else "CUSTOMER"
        lines.append(f"{role}: {t.get('text', '')}")
    return "\n".join(lines)


async def extract_lead_and_summary(turns: list[dict]) -> tuple[LeadData, str]:
    """Extract the structured lead AND a short summary in a SINGLE Gemini call.

    Returns (lead, summary). This replaces the old two-call flow
    (extract_lead_from_transcript + summarize_transcript), halving the number of
    post-call Gemini requests.

    Retry policy: only retry on transient errors. A quota/429 error means the
    per-minute budget is already exhausted, so we bail immediately rather than
    hammering the API with more requests.
    """
    if not turns:
        return LeadData(), ""

    client = _get_client()
    transcript_text = _format_transcript(turns)

    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=f"{EXTRACTION_PROMPT}\n\nTRANSCRIPT:\n{transcript_text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            raw = response.text or "{}"
            data = json.loads(raw)
            summary = (data.pop("summary", "") or "").strip()
            lead = LeadData(**{k: v for k, v in data.items() if v is not None})
            return lead, summary
        except Exception as e:
            if _is_quota_error(e):
                LOGGER.warning(f"Lead extraction hit quota (429) — not retrying: {e}")
                break
            LOGGER.warning(f"Lead extraction attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s backoff

    return LeadData(), ""
