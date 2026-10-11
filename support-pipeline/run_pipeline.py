#!/usr/bin/env python3
"""Run the full staged pipeline and regenerate every artifact.

  python run_pipeline.py                                   # tickets.json + kb_articles.json -> repo root
  python run_pipeline.py --tickets t.json --kb kb.json --out results
"""
from __future__ import annotations

import argparse
import sys

from support_pipeline.config import DEFAULT_OUT_DIR
from support_pipeline.pipeline import PipelineError, run_pipeline
from support_pipeline.stages.validate import PipelineValidationError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI support-ops pipeline")
    ap.add_argument("--tickets", default="tickets.json")
    ap.add_argument("--kb", default="kb_articles.json")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="folder for generated artifacts (default: repo root)")
    args = ap.parse_args(argv)
    try:
        run_pipeline(args.tickets, args.kb, args.out)
    except (PipelineError, PipelineValidationError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nPipeline complete. See validation_report.md for the check results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
