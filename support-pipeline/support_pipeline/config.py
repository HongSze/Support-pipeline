"""Controlled vocabularies, stage plan, output file names and all scoring/routing constants."""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Controlled vocabularies (every model output is validated against these)
# --------------------------------------------------------------------------- #
INTENTS: tuple[str, ...] = (
    "withdrawal_issue",
    "deposit_issue",
    "login_access",
    "verification_kyc",
    "account_restriction",
    "product_behavior",
    "privacy_request",
    "statement_export",
    "api_support",
    "other",
)
URGENCIES: tuple[str, ...] = ("critical", "high", "medium", "low")
SENTIMENTS: tuple[str, ...] = ("calm", "frustrated", "angry", "neutral")
QUEUES: tuple[str, ...] = (
    "General Support",
    "Payments",
    "Compliance",
    "Risk",
    "Engineering",
    "Product",
    "Privacy",
    "Developer Support",
)
# Ordered least -> most restrictive; code can only make a label stricter.
SAFETY_LABELS: tuple[str, ...] = (
    "safe_to_send_after_review",
    "needs_specialist_review",
    "needs_legal_or_compliance_review",
)
SAFETY_SEVERITY: dict[str, int] = {label: i for i, label in enumerate(SAFETY_LABELS)}

# --------------------------------------------------------------------------- #
# Pipeline state machine
# --------------------------------------------------------------------------- #
STATES: tuple[str, ...] = (
    "INIT",
    "TICKETS_LOADED",
    "PREPROCESSING_COMPLETE",
    "TICKETS_CLASSIFIED",
    "KB_RETRIEVAL_COMPLETE",
    "PRIORITY_SCORES_COMPUTED",
    "ROUTING_COMPLETE",
    "REPLY_DRAFTS_GENERATED",
    "VALIDATION_COMPLETE",
    "RESULTS_FINALISED",
)
# (stage name, required state, resulting state)
STAGE_PLAN: tuple[tuple[str, str, str], ...] = (
    ("load",       "INIT",                     "TICKETS_LOADED"),
    ("preprocess", "TICKETS_LOADED",           "PREPROCESSING_COMPLETE"),
    ("classify",   "PREPROCESSING_COMPLETE",   "TICKETS_CLASSIFIED"),
    ("retrieve",   "TICKETS_CLASSIFIED",       "KB_RETRIEVAL_COMPLETE"),
    ("priority",   "KB_RETRIEVAL_COMPLETE",    "PRIORITY_SCORES_COMPUTED"),
    ("route",      "PRIORITY_SCORES_COMPUTED", "ROUTING_COMPLETE"),
    ("draft",      "ROUTING_COMPLETE",         "REPLY_DRAFTS_GENERATED"),
    ("validate",   "REPLY_DRAFTS_GENERATED",   "VALIDATION_COMPLETE"),
    ("finalise",   "VALIDATION_COMPLETE",      "RESULTS_FINALISED"),
)

# --------------------------------------------------------------------------- #
# Output files (exactly the ones the specification asks for)
# --------------------------------------------------------------------------- #
PREPROCESSED_FILE = "preprocessed_tickets.json"
CLASSIFIED_FILE = "classified_tickets.json"
RETRIEVAL_FILE = "retrieval_results.json"
PRIORITY_FILE = "priority_scores.json"
ROUTING_FILE = "routing_decisions.json"
DRAFTS_FILE = "reply_drafts.json"
RETRIEVAL_QUALITY_FILE = "retrieval_quality.json"
OPS_SUMMARY_FILE = "ops_summary.md"
HANDOFF_FILE = "handoff_memory.json"
VALIDATION_REPORT_FILE = "validation_report.md"
LLM_LOG_FILE = "llm_calls.jsonl"

DEFAULT_OUT_DIR = "."                   # artifacts are written to the repo root, next to the inputs

CORE_ARTIFACTS: tuple[str, ...] = (PREPROCESSED_FILE, CLASSIFIED_FILE, RETRIEVAL_FILE, PRIORITY_FILE,
                                   ROUTING_FILE, DRAFTS_FILE, LLM_LOG_FILE)
OPTIONAL_ARTIFACTS: tuple[str, ...] = (RETRIEVAL_QUALITY_FILE, OPS_SUMMARY_FILE, HANDOFF_FILE)

# --------------------------------------------------------------------------- #
# Retrieval: BM25 over kb_articles.json only (no hardcoded intent->article maps)
# --------------------------------------------------------------------------- #
RETRIEVAL_TOP_K = 2
TITLE_WEIGHT = 2                    # title repeated N times in the indexed text
TAG_WEIGHT = 3                      # tags repeated N times in the indexed text
BM25_K1 = 1.5
BM25_B = 0.75
SCORE_SATURATION = 4.0              # score = bm25 / (bm25 + SCORE_SATURATION), in [0, 1)
AMBIGUITY_MARGIN = 0.05             # top-2 scores closer than this = ambiguous retrieval

# --------------------------------------------------------------------------- #
# Priority scoring (spec formula, deterministic, no LLM)
# --------------------------------------------------------------------------- #
BASE_PRIORITY: dict[str, int] = {"critical": 40, "high": 25, "medium": 10, "low": 3}
CUSTOMER_TIER_BONUS: dict[str, int] = {"vip": 10, "standard": 0}   # unknown tiers -> 0
FUNDS_BLOCKED_BONUS = 20
REGULATORY_LEGAL_THREAT_BONUS = 25
SPECIALIST_HANDLING_BONUS = 10
RETRIEVAL_WEAKNESS_BONUS = 8
RETRIEVAL_WEAKNESS_THRESHOLD = 0.55
EXPEDITED_TOP_N = 5

# --------------------------------------------------------------------------- #
# Routing guardrails (code) applied on top of the Stage 2 LLM decision
# --------------------------------------------------------------------------- #
INTENT_DEFAULT_QUEUES: dict[str, tuple[str, ...]] = {
    "withdrawal_issue": ("Payments",),
    "deposit_issue": ("Payments",),
    "login_access": ("General Support",),
    "verification_kyc": ("Compliance",),
    "account_restriction": ("Risk", "Compliance"),
    "product_behavior": ("Product",),
    "privacy_request": ("Privacy",),
    "statement_export": ("General Support",),
    "api_support": ("Developer Support",),
    "other": ("General Support",),
}
REQUIRED_QUEUE_RULES: tuple[tuple[str, str], ...] = (
    ("mentions_regulator_or_legal_threat", "Compliance"),
    ("mentions_funds_blocked", "Payments"),
    ("intent:privacy_request", "Privacy"),
    ("intent:verification_kyc", "Compliance"),
    ("intent:account_restriction", "Risk"),
)
MAX_QUEUES_PER_TICKET = 3
MAX_RATIONALE_CHARS = 300
LEGAL_REVIEW_INTENTS = frozenset({"account_restriction", "verification_kyc", "privacy_request"})

# --------------------------------------------------------------------------- #
# LLM (simulated, deterministic — no external model is called)
# --------------------------------------------------------------------------- #
LLM_PROVIDER = "local-simulated"
LLM_MODEL_NAME = "simulated-llm-v1"
LLM_MAX_ATTEMPTS = 2

# Stage names written to llm_calls.jsonl, and the artifact each LLM stage produces.
LLM_STAGE_TRANSLATION = "multilingual_preprocessing"
LLM_STAGE_CLASSIFICATION = "ticket_classification"
LLM_STAGE_ROUTING = "queue_routing"
LLM_STAGE_DRAFTING = "reply_drafting"
LLM_STAGE_HANDOFF = "handoff_memory"
LLM_STAGE_OUTPUTS: dict[str, str] = {
    LLM_STAGE_TRANSLATION: PREPROCESSED_FILE,
    LLM_STAGE_CLASSIFICATION: CLASSIFIED_FILE,
    LLM_STAGE_ROUTING: ROUTING_FILE,
    LLM_STAGE_DRAFTING: DRAFTS_FILE,
    LLM_STAGE_HANDOFF: HANDOFF_FILE,
}
REQUIRED_LLM_STAGES: tuple[str, ...] = (LLM_STAGE_CLASSIFICATION, LLM_STAGE_ROUTING, LLM_STAGE_DRAFTING)
LLM_LOG_REQUIRED_FIELDS: dict[str, type] = {
    "stage": str, "timestamp": str, "provider": str, "model": str,
    "prompt_hash": str, "input_artifacts": list, "output_artifact": str,
}
