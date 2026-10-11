"""Input schema validation for tickets.json and kb_articles.json (used by the load stage and the checker)."""
from __future__ import annotations

from datetime import datetime

TICKET_FIELDS: dict[str, type] = {
    "ticket_id": str, "channel": str, "customer_tier": str, "language_hint": str,
    "subject": str, "message": str, "created_at": str,
}
KB_FIELDS: dict[str, type] = {"article_id": str, "title": str, "category": str, "body": str, "tags": list}


def _field_errors(rec, schema: dict[str, type]) -> list[str]:
    if not isinstance(rec, dict):
        return ["record is not a JSON object"]
    errs = []
    for name, typ in schema.items():
        if name not in rec:
            errs.append(f"missing field '{name}'")
        elif not isinstance(rec[name], typ):
            errs.append(f"field '{name}' must be {typ.__name__}")
    return errs


def validate_tickets(raw) -> tuple[list[dict], list[str]]:
    """Return (valid tickets, warnings). customer_tier is lower-cased."""
    if not isinstance(raw, list):
        raise ValueError("tickets file must contain a JSON array")
    valid, warnings, seen = [], [], set()
    for idx, rec in enumerate(raw):
        errs = _field_errors(rec, TICKET_FIELDS)
        if not errs:
            if not rec["ticket_id"].strip():
                errs.append("empty ticket_id")
            if rec["ticket_id"] in seen:
                errs.append("duplicate ticket_id")
            if not (rec["subject"].strip() or rec["message"].strip()):
                errs.append("subject and message are both empty")
            try:
                datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))
            except ValueError:
                errs.append("created_at is not ISO-8601")
        if errs:
            warnings.append(f"ticket #{idx} skipped: {'; '.join(errs)}")
            continue
        seen.add(rec["ticket_id"])
        ticket = {k: rec[k] for k in TICKET_FIELDS}
        ticket["customer_tier"] = ticket["customer_tier"].strip().lower()
        valid.append(ticket)
    return valid, warnings


def validate_kb(raw) -> tuple[list[dict], list[str]]:
    if not isinstance(raw, list):
        raise ValueError("kb file must contain a JSON array")
    valid, warnings, seen = [], [], set()
    for idx, rec in enumerate(raw):
        errs = _field_errors(rec, KB_FIELDS)
        if not errs:
            if not all(isinstance(t, str) for t in rec["tags"]):
                errs.append("tags must be a list of strings")
            if rec["article_id"] in seen:
                errs.append("duplicate article_id")
        if errs:
            warnings.append(f"kb article #{idx} skipped: {'; '.join(errs)}")
            continue
        seen.add(rec["article_id"])
        valid.append({k: rec[k] for k in KB_FIELDS})
    return valid, warnings
