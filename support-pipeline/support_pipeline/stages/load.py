"""INIT -> TICKETS_LOADED

Read tickets.json and kb_articles.json from disk and validate them against the
schema. Malformed records are skipped with a console warning rather than
crashing the run. Nothing is written to disk at this stage.
"""
from __future__ import annotations

from ..io_utils import read_json
from ..schema import validate_kb, validate_tickets


def run(ctx) -> None:
    ctx.tickets, t_warn = validate_tickets(read_json(ctx.tickets_path))
    ctx.kb, k_warn = validate_kb(read_json(ctx.kb_path))
    for w in t_warn + k_warn:
        ctx.log(f"[load] WARNING {w}")
    if not ctx.kb:
        raise ValueError("No valid KB articles loaded; retrieval cannot run")
    ctx.log(f"[load] {len(ctx.tickets)} tickets, {len(ctx.kb)} KB articles")
