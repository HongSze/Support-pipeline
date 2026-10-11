"""Helpers shared by stages."""
from __future__ import annotations


def by_id(records: list[dict]) -> dict[str, dict]:
    return {r["ticket_id"]: r for r in records}
