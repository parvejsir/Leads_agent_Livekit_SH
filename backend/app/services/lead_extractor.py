import asyncio
import json
import time

from google import genai
from google.genai import types

from app.core.config import SETTINGS
from app.core.logging import LOGGER
from app.schemas.lead_schema import LeadData

_client: genai.Client | None = None

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
  "notes": string or null
}
"""


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


SUMMARY_PROMPT = """
You are summarizing a real estate sales phone call between an AI agent (Arjun)
and a customer. Write a concise 1-2 sentence summary of what happened and the
customer's interest. Plain text only — no markdown, no preamble.
"""


async def summarize_transcript(turns: list[dict]) -> str:
    """One-line Gemini summary of the call for the history record. Best-effort."""
    if not turns:
        return ""
    # Need at least one customer turn to be worth summarizing.
    if not any(t.get("role") == "user" for t in turns):
        return ""

    client = _get_client()
    transcript_text = _format_transcript(turns)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=f"{SUMMARY_PROMPT}\n\nTRANSCRIPT:\n{transcript_text}",
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return (response.text or "").strip()
    except Exception as e:
        LOGGER.warning(f"Summary generation failed: {e}")
        return ""


async def extract_lead_from_transcript(turns: list[dict]) -> LeadData:
    if not turns:
        return LeadData()

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
            return LeadData(**{k: v for k, v in data.items() if v is not None})
        except Exception as e:
            LOGGER.warning(f"Lead extraction attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s backoff

    return LeadData()
