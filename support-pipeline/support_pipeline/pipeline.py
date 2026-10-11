"""Orchestrator: runs the stages through the state machine.

INIT -> TICKETS_LOADED -> PREPROCESSING_COMPLETE -> TICKETS_CLASSIFIED
     -> KB_RETRIEVAL_COMPLETE -> PRIORITY_SCORES_COMPUTED -> ROUTING_COMPLETE
     -> REPLY_DRAFTS_GENERATED -> VALIDATION_COMPLETE -> RESULTS_FINALISED

A stage may only run when the pipeline is in its required state, and may only
advance to the very next state. Stages pass data through the spec output files
on disk (each stage reads earlier outputs with ``ctx.load``), so the
intermediate artifacts are preserved and each step is separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import DEFAULT_OUT_DIR, LLM_LOG_FILE, STAGE_PLAN, STATES
from .io_utils import read_json, write_json
from .llm import LLMClient
from .stages import STAGE_FUNCS


class PipelineError(RuntimeError):
    pass


class StateError(PipelineError):
    pass


class PipelineState:
    def __init__(self, log: Callable[[str], None] = print):
        self.current = "INIT"
        self.log = log
        self.log(f"[state] {self.current}")

    def require(self, state: str) -> None:
        if self.current != state:
            raise StateError(f"Stage requires state {state}, but the pipeline is in {self.current}")

    def advance(self, to: str) -> None:
        idx = STATES.index(self.current)
        if idx + 1 >= len(STATES) or STATES[idx + 1] != to:
            raise StateError(f"Illegal transition {self.current} -> {to}")
        self.current = to
        self.log(f"[state] {to}")


@dataclass
class RunContext:
    out_dir: Path
    tickets_path: Path
    kb_path: Path
    llm: LLMClient
    log: Callable[[str], None] = print
    tickets: list[dict] = field(default_factory=list)      # validated input tickets (set by load)
    kb: list[dict] = field(default_factory=list)           # validated KB articles (set by load)

    def path(self, name: str) -> Path:
        return self.out_dir / name

    def load(self, name: str) -> Any:
        p = self.path(name)
        if not p.exists():
            raise PipelineError(f"Missing {p}; the stage that writes it has not run.")
        return read_json(p)

    def save(self, name: str, data: Any) -> Path:
        return write_json(self.path(name), data)

    def save_text(self, name: str, text: str) -> Path:
        p = self.path(name)
        p.write_text(text, encoding="utf-8")
        return p


def run_pipeline(tickets: str | Path = "tickets.json", kb: str | Path = "kb_articles.json",
                 out_dir: str | Path = DEFAULT_OUT_DIR, log: Callable[[str], None] = print) -> Path:
    tickets_path, kb_path = Path(tickets), Path(kb)
    for p in (tickets_path, kb_path):
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ctx = RunContext(out, tickets_path, kb_path, LLMClient(out / LLM_LOG_FILE), log)
    state = PipelineState(log)
    for name, required, resulting in STAGE_PLAN:
        state.require(required)
        STAGE_FUNCS[name](ctx)
        state.advance(resulting)
    return out
