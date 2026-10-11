#!/usr/bin/env python3
"""Validation command: check the generated artifacts and write validation_report.md.

  python validate.py                  # or: make validate
  python validate.py --out results --tickets t.json --kb kb.json

Exit code 0 when every blocking check passes, 1 otherwise. Run the pipeline
first (python run_pipeline.py / make run); `make all` does both.
"""
from __future__ import annotations

import argparse
import sys

from support_pipeline.checks import report_and_raise
from support_pipeline.config import DEFAULT_OUT_DIR


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate support-ops pipeline outputs")
    ap.add_argument("--tickets", default="tickets.json")
    ap.add_argument("--kb", default="kb_articles.json")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="folder containing the generated artifacts")
    args = ap.parse_args(argv)

    checks = report_and_raise(args.out, args.tickets, args.kb, include_optional=True, raise_on_failure=False)
    return 1 if any(not c.passed and c.blocking for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
