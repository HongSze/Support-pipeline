"""REPLY_DRAFTS_GENERATED -> VALIDATION_COMPLETE

Runs the shared checker (support_pipeline/checks.py) over the core outputs on
disk, writes validation_report.md, and stops the run if any check fails. The
finalise stage re-runs the full check set once the optional analysis outputs
exist, and rewrites the report.
"""
from __future__ import annotations

from ..checks import ValidationFailed, report_and_raise

PipelineValidationError = ValidationFailed


def run(ctx) -> None:
    report_and_raise(ctx.out_dir, ctx.tickets_path, ctx.kb_path, include_optional=False, log=ctx.log)
