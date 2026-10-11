"""Deterministic policy rules shared by routing, drafting, validation and the simulated model:
  * minimum reply-safety label from ticket facts
  * queues that must be present for a ticket
  * safety checks on reply text
"""
from __future__ import annotations

import re

from .config import (BASE_PRIORITY, CUSTOMER_TIER_BONUS, EXPEDITED_TOP_N, FUNDS_BLOCKED_BONUS, LEGAL_REVIEW_INTENTS,
                     REGULATORY_LEGAL_THREAT_BONUS, REQUIRED_QUEUE_RULES, RETRIEVAL_WEAKNESS_BONUS,
                     RETRIEVAL_WEAKNESS_THRESHOLD, SAFETY_SEVERITY, SPECIALIST_HANDLING_BONUS)


# --------------------------------------------------------------------------- #
# Priority formula (spec section 4)
# --------------------------------------------------------------------------- #
def compute_priority(*, urgency: str, customer_tier: str, mentions_funds_blocked: bool,
                     mentions_regulator_or_legal_threat: bool, requires_specialist_handling: bool,
                     top_retrieval_score: float) -> int:
    return (
        BASE_PRIORITY[urgency]
        + CUSTOMER_TIER_BONUS.get(customer_tier, 0)
        + (FUNDS_BLOCKED_BONUS if mentions_funds_blocked else 0)
        + (REGULATORY_LEGAL_THREAT_BONUS if mentions_regulator_or_legal_threat else 0)
        + (SPECIALIST_HANDLING_BONUS if requires_specialist_handling else 0)
        + (RETRIEVAL_WEAKNESS_BONUS if top_retrieval_score < RETRIEVAL_WEAKNESS_THRESHOLD else 0)
    )


def top_score(retrieval_record: dict) -> float:
    articles = retrieval_record["retrieved_articles"]
    return articles[0]["score"] if articles else 0.0


def rank_tickets(scored: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """Sort (score, created_at, ticket_id) by score desc, then older first, then id."""
    return sorted(scored, key=lambda r: (-r[0], r[1], r[2]))


def expedited_ids(ranked: list[tuple[int, str, str]]) -> list[str]:
    return [tid for _, _, tid in ranked[:EXPEDITED_TOP_N]]


# --------------------------------------------------------------------------- #
# Routing / safety-label rules
# --------------------------------------------------------------------------- #
def stricter(a: str, b: str) -> str:
    return a if SAFETY_SEVERITY[a] >= SAFETY_SEVERITY[b] else b


def rule_safety_label(*, intent: str, mentions_regulator: bool, requires_specialist: bool,
                      translated: bool, top_score: float) -> str:
    """Minimum label the facts require. The model may go stricter, never looser."""
    if mentions_regulator or intent in LEGAL_REVIEW_INTENTS:
        return "needs_legal_or_compliance_review"
    if requires_specialist or translated or top_score < RETRIEVAL_WEAKNESS_THRESHOLD:
        return "needs_specialist_review"
    return "safe_to_send_after_review"


def required_queues(*, intent: str, mentions_funds_blocked: bool, mentions_regulator: bool) -> list[str]:
    facts = {
        "mentions_funds_blocked": mentions_funds_blocked,
        "mentions_regulator_or_legal_threat": mentions_regulator,
        f"intent:{intent}": True,
    }
    return [queue for condition, queue in REQUIRED_QUEUE_RULES if facts.get(condition)]


SAFETY_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("promise_or_guarantee", re.compile(r"\b(guarantee[ds]?|promise[ds]?|definitely|100%|assure you)\b", re.I)),
    ("outcome_promise", re.compile(
        r"\bwill be (approved|accepted|unblocked|released|refunded|reinstated|restored|credited)\b", re.I)),
    ("timeline_commitment", re.compile(
        r"\b(within|in the next|in) \d+\s*(minutes?|hours?|days?|business days?|working days?)\b", re.I)),
    ("internal_logic_disclosure", re.compile(
        r"\b(flagged (because|due to|by)|triggered by|risk score|fraud (model|system|signal)|our algorithm|"
        r"priority score|internal review logic)\b", re.I)),
    ("speculation", re.compile(r"\b(probably|most likely|i think|i believe|it seems that)\b", re.I)),
    ("legal_advice", re.compile(r"\b(legally (required|entitled)|you (are|aren't|are not) liable|legal advice)\b", re.I)),
    ("credential_request", re.compile(
        r"\b(send|share|provide|tell) (us )?(your )?(password|pin|otp|full card number|cvv)\b", re.I)),
    ("internal_guidance_leak", re.compile(r"\b(support|agents) should\b", re.I)),
    ("pii_echo", re.compile(r"\d[\d -]{7,}\d")),
)


def check_reply_safety(reply: str, citations: list[str], allowed_ids: list[str]) -> list[str]:
    """Return a list of violated rule names (empty = safe)."""
    violations = [f"{rule} ({m.group(0)})" for rule, pattern in SAFETY_RULES if (m := pattern.search(reply))]
    unknown = sorted(set(citations) - set(allowed_ids))
    if unknown:
        violations.append(f"citation_not_retrieved ({', '.join(unknown)})")
    words = len(reply.split())
    if words < 15 or words > 260:
        violations.append(f"length_out_of_bounds ({words} words)")
    return violations
