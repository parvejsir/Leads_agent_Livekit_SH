"""
Bulk contact parsing for the dialing campaign.

Supported: CSV, XLSX, XLS. Apple .numbers is NOT parsed — the proprietary format
is unstable to read; we ask the operator to export to CSV/XLSX instead.

Expected columns (case-insensitive, tolerant of common variants):
  id, customer_name, location, phoneNo

`location` here is the customer's CURRENT location — NOT their preferred property
location (that is discovered during the call). The two are kept strictly separate.
"""

import io
import re
from dataclasses import dataclass

# E.164-ish: optional +, 10–15 digits. Mirrors the frontend's isValidPhone.
_PHONE_RE = re.compile(r"^\+?\d{10,15}$")

# Accepted header aliases → canonical field.
_COLUMN_ALIASES: dict[str, str] = {
    "id": "id",
    "contact_id": "id",
    "customer_name": "name",
    "customername": "name",
    "name": "name",
    "location": "location",
    "city": "location",
    "current_location": "location",
    "phoneno": "phone",
    "phone_no": "phone",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "number": "phone",
}


class UnsupportedFormatError(Exception):
    """Raised for file types we deliberately do not parse (e.g. .numbers)."""


@dataclass
class ContactRow:
    phone: str
    name: str | None
    contact_location: str | None
    contact_id: str | None


@dataclass
class ParseResult:
    contacts: list[ContactRow]
    rejected: list[dict]  # [{row, phone, reason}]


def _normalize_phone(raw: object) -> str:
    """Strip spaces, dashes, parens; keep a single leading +."""
    s = str(raw).strip()
    if s.endswith(".0"):  # Excel often reads phone columns as floats
        s = s[:-2]
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    return ("+" + digits) if plus else digits


def _read_dataframe(filename: str, raw: bytes):
    import pandas as pd  # lazy: only needed for file upload, keeps app boot light

    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    if lower.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(raw), engine="openpyxl", dtype=str)
    if lower.endswith(".xls"):
        return pd.read_excel(io.BytesIO(raw), engine="xlrd", dtype=str)
    if lower.endswith(".numbers"):
        raise UnsupportedFormatError(
            "Apple .numbers files aren't supported. Please export to CSV or XLSX "
            "(File → Export To → CSV/Excel) and upload that."
        )
    raise UnsupportedFormatError(
        f"Unsupported file type: {filename}. Upload a .csv, .xlsx, or .xls file."
    )


def parse_contacts(filename: str, raw: bytes) -> ParseResult:
    df = _read_dataframe(filename, raw)

    # Map headers → canonical names.
    rename: dict[str, str] = {}
    for col in df.columns:
        key = re.sub(r"\s+", "_", str(col).strip().lower())
        if key in _COLUMN_ALIASES:
            rename[col] = _COLUMN_ALIASES[key]
    df = df.rename(columns=rename)

    if "phone" not in df.columns:
        raise UnsupportedFormatError(
            "No phone column found. Expected a 'phoneNo' (or 'phone') column."
        )

    contacts: list[ContactRow] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for idx, row in df.iterrows():
        phone = _normalize_phone(row.get("phone", ""))
        if not phone or not _PHONE_RE.match(phone):
            rejected.append({"row": int(idx) + 2, "phone": phone, "reason": "invalid phone"})
            continue
        key = re.sub(r"\D", "", phone)  # dedupe ignoring +/formatting
        if key in seen:
            rejected.append({"row": int(idx) + 2, "phone": phone, "reason": "duplicate"})
            continue
        seen.add(key)

        def _clean(field: str) -> str | None:
            val = row.get(field)
            if val is None:
                return None
            s = str(val).strip()
            return s or None

        contacts.append(
            ContactRow(
                phone=phone,
                name=_clean("name"),
                contact_location=_clean("location"),
                contact_id=_clean("id"),
            )
        )

    return ParseResult(contacts=contacts, rejected=rejected)
