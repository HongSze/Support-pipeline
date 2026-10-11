"""Deterministic simulated LLM.

No external model is used. This module answers the same five batched tasks the
prompts describe (translate_batch, classify_batch, route_batch, draft_batch,
handoff_batch) in the same JSON shapes, so the pipeline's parsing, vocabulary
validation, retry and logging paths are exercised exactly as they would be with
a real model. It is deliberately simple; the review gates account for its limits.
"""
from __future__ import annotations

import json
import re

from .config import INTENT_DEFAULT_QUEUES, INTENTS, LEGAL_REVIEW_INTENTS
from .policy import required_queues, rule_safety_label
from .risk import RISK_PATTERNS

# --------------------------------------------------------------------------- #
# Translation: glossary gloss (keyword-preserving, not fluent)
# --------------------------------------------------------------------------- #
GLOSSARIES: dict[str, dict[str, str]] = {
    "ms": {
        "disemak semula": "reviewed again", "sebelum ini": "previously", "log masuk": "login",
        "kata laluan": "password", "saya": "I", "sudah": "already", "lulus": "passed",
        "pengesahan": "verification", "tetapi": "but", "sekarang": "now", "diminta": "requested",
        "dokumen": "documents", "tambahan": "additional", "lagi": "again", "kenapa": "why",
        "akaun": "account", "pengeluaran": "withdrawal", "wang": "money", "ditolak": "rejected",
        "digantung": "suspended", "disekat": "blocked", "tutup": "close", "penyata": "statement",
        "tolong": "please", "belum": "not yet", "tidak": "not", "masih": "still", "hari": "days",
    },
    "hi-en": {
        "reflect nahi hua": "not reflected", "wait karna chahiye": "should wait",
        "complaint raise karu": "raise complaint", "cut gaye": "debited", "kat gaye": "debited",
        "nahi hua": "did not happen", "mera": "my", "meri": "my", "mere": "my", "paise": "money",
        "paisa": "money", "mujhe": "I", "nahi": "not", "kya": "", "se": "from", "pe": "on",
        "ya": "or", "karu": "do", "hai": "is", "abhi": "now", "jaldi": "quickly", "band": "blocked",
    },
}


def gloss(text: str, language: str) -> str:
    table = GLOSSARIES.get(language, {})
    out = text
    for src in sorted(table, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(src)}\b", table[src], out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def translate_batch(tickets: list[dict]) -> dict:
    return {"translations": [
        {"ticket_id": t["ticket_id"], "subject_en": gloss(t["subject"], t["source_language"]),
         "message_en": gloss(t["message"], t["source_language"]), "source_language": t["source_language"]}
        for t in tickets
    ]}


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
INTENT_KEYWORDS: dict[str, dict[str, int]] = {
    "withdrawal_issue": {"withdrawal": 3, "withdraw": 3, "payout": 2, "cash out": 2},
    "deposit_issue": {"deposit": 3, "debited": 2, "debit": 2, "debits": 2, "charged": 2,
                      "charged twice": 2, "top up": 2},
    "login_access": {"log in": 3, "login": 3, "sign in": 3, "password": 2, "session": 2,
                     "locked out": 3, "2fa": 2, "two-factor": 2},
    "verification_kyc": {"verification": 3, "verify": 2, "kyc": 3, "proof of address": 4,
                         "documents": 1, "document": 1, "identity": 1, "rejected": 1},
    "account_restriction": {"suspended": 4, "suspension": 4, "restricted": 4, "restriction": 4,
                            "blocked": 2, "frozen": 3},
    "product_behavior": {"bot": 3, "strategy": 2, "backtest": 4, "execution": 2, "live": 1,
                         "performance": 1},
    "privacy_request": {"personal data": 4, "deletion": 3, "delete": 2, "close my account": 3,
                        "closure": 3, "privacy": 3, "gdpr": 3, "retained": 1},
    "statement_export": {"statement": 4, "export": 2, "download": 1, "report": 1},
    "api_support": {"api": 4, "rate limit": 4, "rate limited": 4, "endpoint": 2,
                    "per-token": 1, "per-ip": 1},
}
URGENCY_LADDER = (
    ("critical", re.compile(r"\b(regulator|ombudsman|formal complaint|legal action|lawyer|sue|fraud|"
                            r"unauthori[sz]ed|hacked|stolen)\b")),
    ("high", re.compile(r"\b(urgent(ly)?|immediately|asap|blocked|suspend(ed|ion)?|restrict(ed|ion)?|"
                        r"debit(ed|s)?|charged twice|can'?t log ?in|cannot log ?in|locked out)\b|"
                        r"\bpending (for )?([3-9]|\d{2,}) days\b")),
    ("low", re.compile(r"\b(quick question|where (do|can) i|how (do|can) i)\b")),
)
SENTIMENT_LADDER = (
    ("angry", re.compile(r"\b(regulator|formal complaint|unacceptable|ridiculous|scam|lawyer|"
                         r"immediately|disgusting|worst)\b")),
    ("frustrated", re.compile(r"\b(still|again|twice|keep getting|urgently|why|without a clear reason|"
                              r"pending for|exactly what|already)\b")),
    ("calm", re.compile(r"\b(quick question|thanks|thank you|when you get a chance)\b")),
)


def _has(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text) is not None


def _ladder(ladder, text: str, default: str) -> str:
    for label, pattern in ladder:
        if pattern.search(text):
            return label
    return default


def classify_one(subject: str, message: str) -> dict:
    subj, msg = subject.lower(), message.lower()
    scores = {intent: sum(w * (2 * _has(k, subj) + _has(k, msg)) for k, w in kws.items())
              for intent, kws in INTENT_KEYWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], INTENTS.index(kv[0])))
    top, best = ranked[0]
    intent = top if best > 0 else "other"
    full = f"{subj} {msg}"
    urgency = _ladder(URGENCY_LADDER, full, "medium")
    funds = bool(RISK_PATTERNS["funds_at_risk"].search(full))
    legal = bool(RISK_PATTERNS["regulatory_threat"].search(full))
    security = bool(RISK_PATTERNS["security_concern"].search(full))
    specialist = (intent in LEGAL_REVIEW_INTENTS or intent == "other" or funds or legal or security
                  or urgency == "critical")
    return {
        "intent": intent, "urgency": urgency, "sentiment": _ladder(SENTIMENT_LADDER, full, "neutral"),
        "mentions_funds_blocked": funds, "mentions_regulator_or_legal_threat": legal,
        "requires_specialist_handling": specialist,
    }


def classify_batch(tickets: list[dict]) -> dict:
    return {"classifications": [
        {"ticket_id": t["ticket_id"], **classify_one(t["subject"], t["message"]),
         "original_language": t["original_language"], "translated": t["translated"]}
        for t in tickets
    ]}


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def route_batch(tickets: list[dict]) -> dict:
    out = []
    for t in tickets:
        queues = list(INTENT_DEFAULT_QUEUES[t["intent"]])
        for queue in required_queues(intent=t["intent"], mentions_funds_blocked=t["mentions_funds_blocked"],
                                     mentions_regulator=t["mentions_regulator_or_legal_threat"]):
            if queue not in queues:
                queues.append(queue)
        evidence = [f"intent {t['intent']}, urgency {t['urgency']}"]
        if t["mentions_funds_blocked"]:
            evidence.append("customer reports funds blocked or missing")
        if t["mentions_regulator_or_legal_threat"]:
            evidence.append("mentions regulator or legal action")
        if t["retrieved_articles"]:
            top = t["retrieved_articles"][0]
            evidence.append(f"top KB {top['article_id']} ({top['score']})")
        top_score = t["retrieved_articles"][0]["score"] if t["retrieved_articles"] else 0.0
        label = rule_safety_label(intent=t["intent"], mentions_regulator=t["mentions_regulator_or_legal_threat"],
                                  requires_specialist=t["requires_specialist_handling"],
                                  translated=t["translated"], top_score=top_score)
        out.append({"ticket_id": t["ticket_id"], "queues": queues, "routing_rationale": "; ".join(evidence),
                    "reply_safety_label": label})
    return {"routing_decisions": out}


# --------------------------------------------------------------------------- #
# Drafting: customer-safe templates grounded in the retrieved KB
# --------------------------------------------------------------------------- #
TEMPLATES: dict[str, str] = {
    "withdrawal_issue": (
        "Thanks for getting in touch about your withdrawal, and sorry for the wait. Withdrawals can take "
        "longer than the usual timeframe when an additional verification or security review is needed. "
        "We'll check that the documents you submitted have been received and that your chosen payment "
        "method is eligible for withdrawals. If anything else is needed from you, our payments team will "
        "contact you directly."
    ),
    "deposit_issue": (
        "Sorry to hear that your bank was debited but the deposit isn't showing yet. Some payment methods "
        "take time to reconcile. To help us trace it, please reply with the transaction reference, the "
        "amount, and the date and time of the payment, plus a screenshot or statement line showing the debit "
        "(please hide all but the last four digits of any card or account number). If you were charged more "
        "than once, our payments team will review it with that evidence."
    ),
    "login_access": (
        "Sorry you're having trouble signing in. Invalid-session errors after a password reset are often "
        "caused by an old session or saved credentials. Please sign out on all devices, clear your browser "
        "cache or app data, and sign in again with your new password. If it still fails, reply with your "
        "device, browser or app version and the approximate time of the error so our technical team can "
        "investigate."
    ),
    "verification_kyc": (
        "Thanks for your message about verification. Customers who were verified before can occasionally be "
        "asked for additional documents as part of routine regulatory, risk or account-security checks, and a "
        "request like this doesn't necessarily mean there's a problem with your account. Documents can be "
        "declined if they are outdated, incomplete, cropped, or don't match the details on the account. Our "
        "verification team will review your case and confirm which documents are acceptable."
    ),
    "account_restriction": (
        "We understand how concerning it is when your account is restricted, and we're sorry for the stress "
        "this is causing. Your account is with our specialist team for review. We're not able to share the "
        "internal details of a review, but the team will contact you directly if any further information is "
        "needed from you. We've made sure your message has reached the right team."
    ),
    "product_behavior": (
        "Thanks for the detailed report. Live results can differ from a backtest for several reasons, "
        "including market conditions, latency, slippage, configuration changes and differences in data "
        "assumptions, and we aren't able to predict how a strategy will perform. To check whether anything "
        "changed on our side, please share the strategy name or ID, the time window you compared, and any "
        "configuration changes you made."
    ),
    "privacy_request": (
        "Thanks for your request. We've noted that you'd like to close your account and ask about deletion "
        "of your personal data. To protect your account, we'll first need to verify your identity. Some "
        "information may need to be kept for a period to meet legal and regulatory obligations; our privacy "
        "team will confirm what applies to your account and how the rest of your data will be handled."
    ),
    "statement_export": (
        "You can download your account statement from the Reports or Account History section of your "
        "account: choose the date range you need and export it. If the range you want isn't available in "
        "the app, reply here and we'll explain the options."
    ),
    "api_support": (
        "Thanks for flagging this. Rate limits can vary by endpoint, environment, authentication state and "
        "abuse protections, so they may apply sooner than the general figures in the docs. Please send the "
        "endpoints you're calling, whether requests are authenticated, your approximate request rate, and a "
        "sample rate-limit response (headers and timestamps, with any API keys removed)."
    ),
    "other": (
        "Thanks for reaching out, and sorry for any trouble. We've received your message and passed it to "
        "the right team, who will follow up with you if they need any more details."
    ),
}


def draft_batch(tickets: list[dict]) -> dict:
    out = []
    for t in tickets:
        body = TEMPLATES.get(t["intent"], TEMPLATES["other"])
        if t["channel"] == "email":
            reply = f"Hi there,\n\n{body}\n\nBest regards,\nCustomer Support"
        else:
            reply = f"Hi! {body}"
        note = (f"HUMAN REVIEW REQUIRED before sending ({t['reply_safety_label']}). "
                f"Routed to: {', '.join(t['queues'])}. Check facts against the cited KB and the account record.")
        if t["translated"]:
            note += f" Customer wrote in '{t['original_language']}': confirm reply language and tone."
        out.append({"ticket_id": t["ticket_id"], "channel": t["channel"], "draft_reply": reply,
                    "citations": [a["article_id"] for a in t["kb_articles"][:1]], "review_gate_note": note})
    return {"drafts": out}


# --------------------------------------------------------------------------- #
# Handoff memory
# --------------------------------------------------------------------------- #
OPEN_QUESTIONS: dict[str, list[str]] = {
    "withdrawal_issue": ["Are all requested documents received and accepted?",
                         "Is the payment method eligible for withdrawal?"],
    "deposit_issue": ["What is the transaction reference and amount?",
                      "Has the payment settled with the provider, and is there a duplicate charge?"],
    "login_access": ["Which device, browser or app version is affected?",
                     "Does a clean login after clearing sessions still fail?"],
    "verification_kyc": ["Which document was requested or rejected, and why under the acceptance criteria?"],
    "account_restriction": ["What is the current review status, and does the specialist team need anything?"],
    "product_behavior": ["Which strategy and time window were compared?",
                         "Were there configuration changes or a platform defect?"],
    "privacy_request": ["Has the customer's identity been verified?",
                        "Which data falls under legal retention?"],
    "statement_export": ["Is the requested date range available in-app?"],
    "api_support": ["Which endpoints, auth state and request rate are involved?"],
    "other": ["What exactly does the customer need?"],
}
DO_NOT_SAY_COMMON = [
    "Promises of outcomes, refunds or timelines not stated in the KB",
    "Internal review triggers, risk logic or priority scores",
    "Speculation about the cause",
]
DO_NOT_SAY_INTENT: dict[str, list[str]] = {
    "account_restriction": ["Whether the balance is 'safe' or when the restriction will lift"],
    "verification_kyc": ["That the documents will be approved"],
    "privacy_request": ["Legal guarantees about what data will be deleted"],
    "product_behavior": ["Guarantees about strategy performance"],
}
NEXT_ACTION: dict[str, str] = {
    "withdrawal_issue": "Check the withdrawal review status and document receipt, then update the customer.",
    "deposit_issue": "Collect payment evidence and reconcile with the payment provider; escalate duplicates.",
    "login_access": "Walk through a clean login flow; escalate to Engineering with platform details if it persists.",
    "verification_kyc": "Have Compliance confirm the outstanding document requirement and criteria.",
    "account_restriction": "Specialist team to review the restriction and send an approved written response.",
    "product_behavior": "Collect strategy details; route to Product/Engineering if a platform defect is suspected.",
    "privacy_request": "Verify identity, then hand to the Privacy team for closure and deletion handling.",
    "statement_export": "Point the customer to Reports/Account History and explain export limits if needed.",
    "api_support": "Collect request context and route persistent discrepancies for technical review.",
    "other": "Clarify the request and route to the right team.",
}


def handoff_one(t: dict) -> dict:
    intent = t["intent"]
    summary = f"{t['subject'].rstrip('.?!')}: {t['message']}"
    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."
    return {
        "ticket_id": t["ticket_id"],
        "customer_problem_summary": summary,
        "open_questions": OPEN_QUESTIONS.get(intent, OPEN_QUESTIONS["other"]),
        "do_not_say": DO_NOT_SAY_COMMON + DO_NOT_SAY_INTENT.get(intent, []),
        "recommended_next_action": NEXT_ACTION.get(intent, NEXT_ACTION["other"]),
    }


def handoff_batch(tickets: list[dict]) -> dict:
    return {"handoffs": [handoff_one(t) for t in tickets]}


# --------------------------------------------------------------------------- #
TASKS = {
    "translate_batch": translate_batch,
    "classify_batch": classify_batch,
    "route_batch": route_batch,
    "draft_batch": draft_batch,
    "handoff_batch": handoff_batch,
}


def respond(task: str, payload: dict) -> str:
    if task not in TASKS:
        raise ValueError(f"offline backend has no task '{task}'")
    return json.dumps(TASKS[task](payload["tickets"]), ensure_ascii=False)
