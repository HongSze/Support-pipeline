"""KB_RETRIEVAL_COMPLETE -> PRIORITY_SCORES_COMPUTED

Spec formula, computed in code (the LLM never assigns priority) — see
policy.compute_priority:

  priority_score = base priority (critical 40 / high 25 / medium 10 / low 3)
                 + customer tier bonus (vip 10 / standard 0)
                 + 20 if mentions_funds_blocked
                 + 25 if mentions_regulator_or_legal_threat
                 + 10 if requires_specialist_handling
                 + 8  if top retrieval score < 0.55

Sorted by priority_score descending; ties break by created_at (older first),
then ticket_id. The top 5 are flagged expedited.

Output: priority_scores.json
"""
from __future__ import annotations

from ..config import CLASSIFIED_FILE, PRIORITY_FILE, RETRIEVAL_FILE
from ..policy import compute_priority, expedited_ids, rank_tickets, top_score
from .common import by_id


def run(ctx) -> None:
    tickets = by_id(ctx.tickets)
    retrieval = by_id(ctx.load(RETRIEVAL_FILE))
    scored = []
    for c in ctx.load(CLASSIFIED_FILE):
        tid = c["ticket_id"]
        score = compute_priority(
            urgency=c["urgency"], customer_tier=tickets[tid]["customer_tier"],
            mentions_funds_blocked=c["mentions_funds_blocked"],
            mentions_regulator_or_legal_threat=c["mentions_regulator_or_legal_threat"],
            requires_specialist_handling=c["requires_specialist_handling"],
            top_retrieval_score=top_score(retrieval[tid]),
        )
        scored.append((score, tickets[tid]["created_at"], tid))

    ranked = rank_tickets(scored)
    top = set(expedited_ids(ranked))
    records = [{"ticket_id": tid, "priority_score": score, "expedited": tid in top} for score, _, tid in ranked]
    ctx.save(PRIORITY_FILE, records)
    ctx.log(f"[priority] expedited: {', '.join(r['ticket_id'] for r in records if r['expedited'])} -> {PRIORITY_FILE}")
