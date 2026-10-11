"""Deterministic risk-flag regexes (code, not model). Shared by stages and the offline backend."""
from __future__ import annotations

import re

RISK_PATTERNS: dict[str, re.Pattern] = {
    "regulatory_threat": re.compile(
        r"\b(regulator|ombudsman|formal complaint|legal action|lawyer|solicitor|sue|court)\b"),
    "funds_at_risk": re.compile(
        r"\b(funds?|balance|money|deposit|withdrawal)\b.{0,40}\b(blocked|frozen|stuck|safe|missing|"
        r"debited|lost|pending)\b|\bcharged twice\b|\b(two|double|duplicate)\b.{0,20}\b(debits?|charges?)\b|"
        r"\bdebited\b"),
    "security_concern": re.compile(
        r"\b(hacked|unauthori[sz]ed|stolen|phishing|compromised)\b|someone else (logged|accessed)"),
    "privacy_legal": re.compile(
        r"\b(personal data|data deletion|gdpr|delete (my )?(personal )?data|retain(ed)? for legal)\b"),
}


def detect_risk_flags(text: str) -> list[str]:
    """Risk flags in a fixed order."""
    text = text.lower()
    return [name for name, pattern in RISK_PATTERNS.items() if pattern.search(text)]
