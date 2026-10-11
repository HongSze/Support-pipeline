"""LLM client: prompt -> JSON -> vocabulary validation -> retry, with every call logged.

No external model is called. Responses come from the deterministic simulated
model in ``simulated_model.py``, which reads the structured payload and returns
the same JSON shape the prompt asks for. Prompts are still built in full
(schema fields, controlled vocabularies, rules), so a real model could replace
``SimulatedModel.generate`` without changing the pipeline.

Every call (including retries) appends one JSON object to ``llm_calls.jsonl``:
  stage, timestamp (ISO-8601), provider, model, prompt_hash,
  input_artifacts, output_artifact
plus task / attempt / valid / validation_errors for traceability.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import simulated_model
from .config import LLM_MAX_ATTEMPTS, LLM_MODEL_NAME, LLM_PROVIDER
from .io_utils import sha256_text

Validator = Callable[[Any], list]


class SimulatedModel:
    provider = LLM_PROVIDER
    name = LLM_MODEL_NAME

    def generate(self, task: str, system: str, user: str, payload: dict) -> str:
        return simulated_model.respond(task, payload)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(raw: str) -> tuple[Any, str | None]:
    text = _FENCE.sub("", raw.strip())
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None, "response is not JSON"
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON: {exc.msg}"
    if not isinstance(obj, dict):
        return None, "response JSON is not an object"
    return obj, None


class LLMClient:
    def __init__(self, log_path: str | Path, model: SimulatedModel | None = None):
        self.model = model or SimulatedModel()
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")       # fresh log per run

    def _log(self, record: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def complete_json(self, *, stage: str, task: str, system: str, user: str, payload: dict,
                      validator: Validator, input_artifacts: list[str], output_artifact: str,
                      max_attempts: int = LLM_MAX_ATTEMPTS) -> tuple[dict | None, bool]:
        """Call the model, parse JSON, validate; on failure retry once with the errors fed back.

        Returns ``(parsed, valid)``. When every attempt fails, ``parsed`` is the last
        parseable response (or None) so callers can keep its valid parts.
        """
        errors: list[str] = []
        last_parsed = None
        for attempt in range(1, max_attempts + 1):
            prompt = user if attempt == 1 else (
                f"{user}\n\nYOUR PREVIOUS RESPONSE WAS REJECTED: {'; '.join(errors)}\n"
                "Return ONLY one JSON object that satisfies the schema and allowed values.")
            raw, error = None, None
            try:
                raw = self.model.generate(task, system, prompt, payload)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            parsed = None
            if raw is None:
                errors = [f"model error: {error}"]
            else:
                parsed, parse_error = parse_json_object(raw)
                errors = [parse_error] if parse_error else list(validator(parsed))
                if parsed is not None:
                    last_parsed = parsed

            self._log({
                "stage": stage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": self.model.provider,
                "model": self.model.name,
                "prompt_hash": sha256_text(f"{system}\n\n{prompt}"),
                "input_artifacts": [str(p) for p in input_artifacts],
                "output_artifact": str(output_artifact),
                "task": task,
                "attempt": attempt,
                "valid": not errors,
                "validation_errors": errors,
            })
            if not errors:
                return parsed, True
        return last_parsed, False
