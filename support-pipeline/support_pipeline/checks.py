"""Validation checks + validation_report.md.

Used by three entry points, so they all check exactly the same things:
  * the pipeline's VALIDATION_COMPLETE stage   (core outputs; stops the run on failure)
  * the RESULTS_FINALISED stage                (full set incl. optional analysis outputs)
  * `python validate.py` / `make validate`     (standalone, from files on disk)

Everything is read back from disk; nothing is trusted from pipeline memory.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import (CLASSIFIED_FILE, CORE_ARTIFACTS, DRAFTS_FILE, HANDOFF_FILE, INTENTS, LLM_LOG_FILE,
                     LLM_LOG_REQUIRED_FIELDS, LLM_STAGE_HANDOFF, LLM_STAGE_OUTPUTS, LLM_STAGE_TRANSLATION,
                     OPS_SUMMARY_FILE, OPTIONAL_ARTIFACTS, PREPROCESSED_FILE, PRIORITY_FILE, QUEUES,
                     REQUIRED_LLM_STAGES, RETRIEVAL_FILE, RETRIEVAL_QUALITY_FILE, RETRIEVAL_TOP_K, ROUTING_FILE,
                     SAFETY_LABELS, SAFETY_SEVERITY, SENTIMENTS, URGENCIES, VALIDATION_REPORT_FILE)
from .policy import (check_reply_safety, compute_priority, expedited_ids, rank_tickets, required_queues,
                     rule_safety_label, top_score)
from .schema import validate_kb, validate_tickets

PREPROCESSED_FIELDS = ("ticket_id", "original_subject", "original_message", "subject_for_processing",
                       "message_for_processing", "original_language", "translated")
CLASSIFIED_FIELDS = ("ticket_id", "intent", "urgency", "sentiment", "mentions_funds_blocked",
                     "mentions_regulator_or_legal_threat", "requires_specialist_handling",
                     "original_language", "translated")
BOOL_FIELDS = ("mentions_funds_blocked", "mentions_regulator_or_legal_threat", "requires_specialist_handling")
DRAFT_FIELDS = ("ticket_id", "channel", "draft_reply", "citations", "review_gate_note")
ROUTING_FIELDS = ("ticket_id", "queues", "routing_rationale", "reply_safety_label")
HANDOFF_FIELDS = ("ticket_id", "customer_problem_summary", "open_questions", "do_not_say", "recommended_next_action")
QUALITY_FIELDS = ("ticket_id", "issue", "recommended_improvement")


class ValidationFailed(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    spec: bool            # True = listed in the specification; False = additional check
    passed: bool
    details: list[str]
    blocking: bool = True  # non-blocking checks report WARN and never fail the run


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def run_checks(out_dir: str | Path, tickets_path: str | Path, kb_path: str | Path,
               include_optional: bool = True) -> list[Check]:
    out = Path(out_dir)
    checks: list[Check] = []

    def add(name: str, problems: list[str], ok_note: str, *, spec: bool = True, blocking: bool = True) -> None:
        checks.append(Check(name, spec, not problems, problems or [ok_note], blocking))

    artifacts = list(CORE_ARTIFACTS) + (list(OPTIONAL_ARTIFACTS) if include_optional else [])
    paths: dict[str, Path] = {"tickets": Path(tickets_path), "kb": Path(kb_path)}
    paths.update({name: out / name for name in artifacts})

    # 1. Required artifacts exist ------------------------------------------------
    missing = [str(p) for p in paths.values() if not p.exists()]
    add("Required artifacts exist", [f"missing: {m}" for m in missing], f"all {len(paths)} artifacts present")

    # 2. JSON files are valid ----------------------------------------------------
    data: dict[str, Any] = {}
    problems = []
    for key, p in paths.items():
        if not p.exists() or p.suffix not in (".json", ".jsonl"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
            if p.suffix == ".json":
                data[key] = json.loads(text)
            else:
                records = []
                for n, line in enumerate(text.splitlines(), start=1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"line {n}: {exc.msg}") from None
                    if not isinstance(obj, dict):
                        raise ValueError(f"line {n}: not a JSON object")
                    records.append(obj)
                data[key] = records
        except (ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{p}: {exc}")
    add("JSON files are valid", problems, f"{len(data)} JSON/JSONL files parsed")

    # Inputs (schema-validated exactly as the pipeline does) ---------------------
    try:
        tickets = validate_tickets(data["tickets"])[0] if "tickets" in data else []
    except ValueError:
        tickets = []
    try:
        kb = validate_kb(data["kb"])[0] if "kb" in data else []
    except ValueError:
        kb = []
    expected_ids = [t["ticket_id"] for t in tickets]
    tickets_by_id = {t["ticket_id"]: t for t in tickets}
    kb_by_id = {a["article_id"]: a for a in kb}

    def records(key: str) -> list[dict] | None:
        val = data.get(key)
        if isinstance(val, list) and all(isinstance(r, dict) and isinstance(r.get("ticket_id"), str) for r in val):
            return val
        return None

    def index(key: str) -> dict[str, dict]:
        return {r["ticket_id"]: r for r in (records(key) or [])}

    pre, cls, ret, pri_list, rte, drf = (index(PREPROCESSED_FILE), index(CLASSIFIED_FILE), index(RETRIEVAL_FILE),
                                         records(PRIORITY_FILE) or [], index(ROUTING_FILE), index(DRAFTS_FILE))

    # 3. All tickets were processed ----------------------------------------------
    problems = [] if tickets else ["no valid tickets found in tickets.json"]
    for key in (PREPROCESSED_FILE, CLASSIFIED_FILE, RETRIEVAL_FILE, PRIORITY_FILE, ROUTING_FILE):
        recs = records(key)
        if recs is None:
            problems.append(f"{key}: missing or not a list of ticket records")
            continue
        ids = [r["ticket_id"] for r in recs]
        lost = sorted(set(expected_ids) - set(ids))
        extra = sorted(set(ids) - set(expected_ids))
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if lost:
            problems.append(f"{key}: missing tickets {lost}")
        if extra:
            problems.append(f"{key}: unknown tickets {extra}")
        if dupes:
            problems.append(f"{key}: duplicated tickets {dupes}")
    add("All tickets were processed", problems,
        f"{len(expected_ids)} tickets appear exactly once in each per-ticket output")

    # 4. Non-English / mixed-language tickets ------------------------------------
    problems, n_non_en = [], 0
    for t in tickets:
        tid = t["ticket_id"]
        p = pre.get(tid)
        if p is None:
            problems.append(f"{tid}: not in {PREPROCESSED_FILE}")
            continue
        absent = [f for f in PREPROCESSED_FIELDS if f not in p]
        if absent:
            problems.append(f"{tid}: missing fields {absent}")
            continue
        non_english = t["language_hint"].strip().lower() not in ("", "en") or p["original_language"] != "en"
        if not non_english:
            continue
        n_non_en += 1
        if p["original_subject"] != t["subject"] or p["original_message"] != t["message"]:
            problems.append(f"{tid}: original text not preserved")
        if p["translated"] is not True:
            problems.append(f"{tid}: non-English ticket not marked translated")
        msg = p["message_for_processing"]
        if not isinstance(msg, str) or not msg.strip():
            problems.append(f"{tid}: missing English processing text")
        elif msg.strip() == t["message"].strip():
            problems.append(f"{tid}: processing text identical to the original (not translated)")
    add("Non-English / mixed-language tickets preserve original text and include English processing text",
        problems, f"{n_non_en} non-English or mixed-language ticket(s) verified")

    # 5. Classified outputs use only controlled vocabularies ---------------------
    problems = []
    for tid, c in cls.items():
        absent = [f for f in CLASSIFIED_FIELDS if f not in c]
        if absent:
            problems.append(f"{tid}: missing fields {absent}")
            continue
        for key, allowed in (("intent", INTENTS), ("urgency", URGENCIES), ("sentiment", SENTIMENTS)):
            if c[key] not in allowed:
                problems.append(f"{tid}: {key} {c[key]!r} not in controlled vocabulary")
        for key in BOOL_FIELDS:
            if not isinstance(c[key], bool):
                problems.append(f"{tid}: {key} must be a boolean")
        if tid in pre and (c["original_language"] != pre[tid].get("original_language")
                           or c["translated"] != pre[tid].get("translated")):
            problems.append(f"{tid}: original_language/translated disagree with {PREPROCESSED_FILE}")
    if not cls:
        problems.append(f"{CLASSIFIED_FILE}: no classified tickets")
    add("Classified outputs use only controlled vocabularies", problems,
        f"{len(cls)} classifications use allowed intent / urgency / sentiment values")

    # 6. Retrieval references valid KB article IDs -------------------------------
    # 7. Exactly 2 retrieved articles per ticket ---------------------------------
    p6, p7 = [], []
    want = min(RETRIEVAL_TOP_K, len(kb))
    for tid, r in ret.items():
        arts = r.get("retrieved_articles")
        if not isinstance(arts, list):
            p6.append(f"{tid}: retrieved_articles missing")
            p7.append(f"{tid}: retrieved_articles missing")
            continue
        if len(arts) != want:
            p7.append(f"{tid}: {len(arts)} articles (expected {want})")
        ids = [a.get("article_id") for a in arts if isinstance(a, dict)]
        if len(ids) != len(set(ids)):
            p7.append(f"{tid}: duplicate articles")
        for a in arts:
            if not isinstance(a, dict) or a.get("article_id") not in kb_by_id:
                p6.append(f"{tid}: unknown article {a.get('article_id') if isinstance(a, dict) else a!r}")
                continue
            if a.get("title") != kb_by_id[a["article_id"]]["title"]:
                p6.append(f"{tid}: title for {a['article_id']} does not match kb_articles.json")
            score = a.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
                p6.append(f"{tid}: score for {a['article_id']} must be a number in [0, 1]")
    if not ret:
        p6.append(f"{RETRIEVAL_FILE}: no retrieval results")
        p7.append(f"{RETRIEVAL_FILE}: no retrieval results")
    add("Retrieval results reference valid article IDs from kb_articles.json", p6,
        f"all retrieved articles exist in kb_articles.json ({len(kb)} articles)")
    add("Each ticket has exactly 2 retrieved articles", p7, f"{len(ret)} tickets x {want} articles")

    # 8. Priority computed deterministically after retrieval --------------------
    # 9. Top 5 expedited selected from computed scores --------------------------
    p8, p9, recomputed = [], [], []
    for r in pri_list:
        tid = r["ticket_id"]
        if tid not in cls or tid not in ret or tid not in tickets_by_id:
            p8.append(f"{tid}: cannot recompute (missing classification, retrieval or ticket)")
            continue
        c = cls[tid]
        try:
            score = compute_priority(
                urgency=c["urgency"], customer_tier=tickets_by_id[tid]["customer_tier"],
                mentions_funds_blocked=c["mentions_funds_blocked"],
                mentions_regulator_or_legal_threat=c["mentions_regulator_or_legal_threat"],
                requires_specialist_handling=c["requires_specialist_handling"],
                top_retrieval_score=top_score(ret[tid]),
            )
        except (KeyError, TypeError, IndexError) as exc:
            p8.append(f"{tid}: cannot recompute ({exc})")
            continue
        recomputed.append((score, tickets_by_id[tid]["created_at"], tid))
        if r.get("priority_score") != score:
            p8.append(f"{tid}: priority_score {r.get('priority_score')} != formula {score}")
    file_scores = [r.get("priority_score") for r in pri_list]
    if all(isinstance(s, (int, float)) for s in file_scores) and file_scores != sorted(file_scores, reverse=True):
        p8.append(f"{PRIORITY_FILE} is not sorted by priority_score descending")
    if paths[RETRIEVAL_FILE].exists() and paths[PRIORITY_FILE].exists() \
            and os.path.getmtime(paths[PRIORITY_FILE]) < os.path.getmtime(paths[RETRIEVAL_FILE]):
        p8.append(f"{PRIORITY_FILE} is older than {RETRIEVAL_FILE} (not computed after retrieval)")
    if not pri_list:
        p8.append(f"{PRIORITY_FILE}: no priority scores")
    add("Priority scores are computed deterministically after retrieval", p8,
        f"{len(recomputed)} scores match the formula, sorted descending, written after retrieval")

    expected_top = expedited_ids(rank_tickets(recomputed))
    actual_top = [r["ticket_id"] for r in pri_list if r.get("expedited") is True]
    if sorted(actual_top) != sorted(expected_top):
        p9.append(f"expedited {actual_top} but top by computed score is {expected_top}")
    if any(not isinstance(r.get("expedited"), bool) for r in pri_list):
        p9.append("every priority record needs a boolean 'expedited'")
    add("Top 5 expedited tickets are selected from computed scores", p9,
        f"expedited: {', '.join(expected_top) or 'none'}")

    # 10. Routing queues use only the controlled queue vocabulary ---------------
    problems = []
    for tid, rt in rte.items():
        absent = [f for f in ROUTING_FIELDS if f not in rt]
        if absent:
            problems.append(f"{tid}: missing fields {absent}")
            continue
        queues = rt["queues"]
        if not isinstance(queues, list) or not queues:
            problems.append(f"{tid}: queues must be a non-empty list")
            continue
        bad = [q for q in queues if q not in QUEUES]
        if bad:
            problems.append(f"{tid}: queues {bad} not in controlled vocabulary")
        if rt["reply_safety_label"] not in SAFETY_LABELS:
            problems.append(f"{tid}: reply_safety_label {rt['reply_safety_label']!r} not in controlled vocabulary")
        if not isinstance(rt["routing_rationale"], str) or not rt["routing_rationale"].strip():
            problems.append(f"{tid}: empty routing_rationale")
    if not rte:
        problems.append(f"{ROUTING_FILE}: no routing decisions")
    add("Routing queues use only the controlled queue vocabulary", problems,
        f"{len(rte)} routing decisions use allowed queues and safety labels")

    # 11. Reply drafts exist for all top 5 --------------------------------------
    problems = []
    drafts_list = records(DRAFTS_FILE) or []
    for tid in expected_top:
        if tid not in drf:
            problems.append(f"{tid}: no reply draft")
    extra = sorted(set(drf) - set(expected_top))
    if extra:
        problems.append(f"drafts for non-top-5 tickets: {extra}")
    for d in drafts_list:
        absent = [f for f in DRAFT_FIELDS if f not in d]
        if absent:
            problems.append(f"{d['ticket_id']}: missing fields {absent}")
    add("Reply drafts exist for all top 5 priority tickets", problems,
        f"{len(drf)} drafts, one per expedited ticket")

    # 12. Reply drafts cite retrieved KB articles -------------------------------
    problems = []
    for tid, d in drf.items():
        cites = d.get("citations")
        allowed = [a.get("article_id") for a in (ret.get(tid) or {}).get("retrieved_articles", [])
                   if isinstance(a, dict)]
        if not isinstance(cites, list) or not cites:
            problems.append(f"{tid}: no citations")
            continue
        bad = [c for c in cites if c not in allowed]
        if bad:
            problems.append(f"{tid}: cites {bad}, not among retrieved {allowed}")
    if not drf:
        problems.append(f"{DRAFTS_FILE}: no drafts")
    add("Reply drafts cite retrieved KB articles", problems,
        "every draft cites only articles retrieved for its ticket")

    # 13. LLM call logs have separate records for required stages ---------------
    problems = []
    log = data.get(LLM_LOG_FILE)
    if not isinstance(log, list) or not log:
        problems.append(f"{LLM_LOG_FILE}: missing or empty")
        log = []
    required_stages = list(REQUIRED_LLM_STAGES)
    if any(p.get("translated") is True for p in pre.values()):
        required_stages.insert(0, LLM_STAGE_TRANSLATION)
    if include_optional and HANDOFF_FILE in paths and paths[HANDOFF_FILE].exists():
        required_stages.append(LLM_STAGE_HANDOFF)
    present = [rec.get("stage") for rec in log]
    for stage in required_stages:
        if stage not in present:
            problems.append(f"no log record for stage '{stage}'")
    for n, rec in enumerate(log, start=1):
        for field, typ in LLM_LOG_REQUIRED_FIELDS.items():
            if field not in rec:
                problems.append(f"record {n}: missing '{field}'")
            elif not isinstance(rec[field], typ):
                problems.append(f"record {n}: '{field}' must be {typ.__name__}")
        ts = rec.get("timestamp")
        if isinstance(ts, str):
            try:
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                problems.append(f"record {n}: timestamp is not ISO-8601")
        if isinstance(rec.get("input_artifacts"), list) and not all(isinstance(a, str) for a in rec["input_artifacts"]):
            problems.append(f"record {n}: input_artifacts must be paths (strings)")
        stage, output = rec.get("stage"), rec.get("output_artifact")
        if stage in LLM_STAGE_OUTPUTS and isinstance(output, str) and Path(output).name != LLM_STAGE_OUTPUTS[stage]:
            problems.append(f"record {n}: stage '{stage}' should output {LLM_STAGE_OUTPUTS[stage]}, got {output}")
    add("LLM call logs contain separate records for required stages", problems,
        f"{len(log)} records; stages: {', '.join(dict.fromkeys(s for s in present if s))}")

    # ---------------------------- additional checks ----------------------------
    problems = []
    for tid, rt in rte.items():
        c, p = cls.get(tid), pre.get(tid)
        if not c or not p or tid not in ret or not isinstance(rt.get("queues"), list):
            continue
        for queue in required_queues(intent=c["intent"], mentions_funds_blocked=c["mentions_funds_blocked"],
                                     mentions_regulator=c["mentions_regulator_or_legal_threat"]):
            if queue not in rt["queues"]:
                problems.append(f"{tid}: required queue {queue} missing")
        minimum = rule_safety_label(intent=c["intent"], mentions_regulator=c["mentions_regulator_or_legal_threat"],
                                    requires_specialist=c["requires_specialist_handling"],
                                    translated=p.get("translated", False), top_score=top_score(ret[tid]))
        label = rt.get("reply_safety_label")
        if label in SAFETY_SEVERITY and SAFETY_SEVERITY[label] < SAFETY_SEVERITY[minimum]:
            problems.append(f"{tid}: reply_safety_label {label} is below the rule minimum {minimum}")
    add("Routing guardrails applied (required queues, minimum safety label)", problems,
        "required queues present and no safety label below the rule minimum", spec=False)

    problems = []
    for tid, d in drf.items():
        if tid in tickets_by_id and d.get("channel") != tickets_by_id[tid]["channel"]:
            problems.append(f"{tid}: channel {d.get('channel')!r} does not match the ticket")
        if not isinstance(d.get("review_gate_note"), str) or not d["review_gate_note"].strip():
            problems.append(f"{tid}: missing review_gate_note")
    add("Reply drafts include channel and a human review gate note", problems,
        "every draft has the ticket's channel and a review gate note", spec=False)

    problems = []
    for tid, d in drf.items():
        reply = d.get("draft_reply")
        allowed = [a.get("article_id") for a in (ret.get(tid) or {}).get("retrieved_articles", [])
                   if isinstance(a, dict)]
        if not isinstance(reply, str):
            problems.append(f"{tid}: draft_reply missing")
            continue
        problems += [f"{tid}: {v}" for v in check_reply_safety(reply, d.get("citations") or [], allowed)]
    add("Reply drafts pass safety rules (no promises, timelines, speculation, internal logic)", problems,
        "no safety-rule hits", spec=False, blocking=False)

    if include_optional:
        problems = []
        quality = data.get(RETRIEVAL_QUALITY_FILE)
        if not isinstance(quality, list):
            problems.append(f"{RETRIEVAL_QUALITY_FILE}: must be a list")
        else:
            for q in quality:
                if not isinstance(q, dict) or any(not isinstance(q.get(f), str) or not q.get(f) for f in QUALITY_FIELDS):
                    problems.append(f"{RETRIEVAL_QUALITY_FILE}: entry missing {list(QUALITY_FIELDS)}")
                elif q["ticket_id"] not in tickets_by_id:
                    problems.append(f"{RETRIEVAL_QUALITY_FILE}: unknown ticket {q['ticket_id']}")
        handoff = data.get(HANDOFF_FILE)
        if not isinstance(handoff, list):
            problems.append(f"{HANDOFF_FILE}: must be a list")
        else:
            ids = [h.get("ticket_id") for h in handoff if isinstance(h, dict)]
            if sorted(ids) != sorted(expected_top):
                problems.append(f"{HANDOFF_FILE}: should cover exactly the top 5 {expected_top}, got {ids}")
            for h in handoff:
                if not isinstance(h, dict) or any(f not in h for f in HANDOFF_FIELDS) \
                        or not isinstance(h.get("open_questions"), list) or not isinstance(h.get("do_not_say"), list):
                    problems.append(f"{HANDOFF_FILE}: entry missing or mistyped fields {list(HANDOFF_FIELDS)}")
        ops = paths[OPS_SUMMARY_FILE]
        if ops.exists():
            text = ops.read_text(encoding="utf-8")
            for heading in ("Count by intent", "Count by urgency", "recurring problem themes",
                            "legal / regulatory risk", "specialist handling"):
                if heading.lower() not in text.lower():
                    problems.append(f"{OPS_SUMMARY_FILE}: missing section '{heading}'")
        add("Optional analysis outputs are well-formed", problems,
            f"{RETRIEVAL_QUALITY_FILE}, {OPS_SUMMARY_FILE} and {HANDOFF_FILE} match their schemas", spec=False)

    return checks


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _cell(text: str, limit: int = 140) -> str:
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _status(c: Check) -> str:
    return "PASS" if c.passed else ("FAIL" if c.blocking else "WARN")


def render_report(checks: list[Check], *, tickets_path, kb_path, include_optional: bool) -> str:
    failed = [c for c in checks if not c.passed and c.blocking]
    warned = [c for c in checks if not c.passed and not c.blocking]
    passed = sum(c.passed for c in checks)
    result = "PASSED" if not failed else "FAILED"

    def table(rows: list[Check], start: int) -> list[str]:
        out = ["| # | Check | Result | Details |", "|---|---|---|---|"]
        for i, c in enumerate(rows, start=start):
            detail = c.details[0] + (f" (+{len(c.details) - 1} more)" if len(c.details) > 1 else "")
            out.append(f"| {i} | {_cell(c.name, 200)} | **{_status(c)}** | {_cell(detail)} |")
        return out

    spec_checks = [c for c in checks if c.spec]
    extra_checks = [c for c in checks if not c.spec]
    lines = [
        "# Validation Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Inputs: `{tickets_path}`, `{kb_path}`",
        f"- Scope: {'full run (core outputs + optional analysis outputs)' if include_optional else 'core pipeline outputs'}",
        f"- Result: **{result}** — {passed}/{len(checks)} checks passed"
        + (f", {len(failed)} failed" if failed else "") + (f", {len(warned)} warning(s)" if warned else ""),
        "",
        "## Specification checks",
        "",
        *table(spec_checks, 1),
        "",
        "## Additional checks",
        "",
        *table(extra_checks, len(spec_checks) + 1),
        "",
    ]
    attention = failed + warned
    if attention:
        lines += ["## Failures and warnings", ""]
        for c in attention:
            lines += [f"### {_status(c)}: {c.name}", ""]
            lines += [f"- {_cell(d, 400)}" for d in c.details[:50]]
            if len(c.details) > 50:
                lines.append(f"- ... and {len(c.details) - 50} more")
            lines.append("")
    else:
        lines += ["All checks passed. Reply drafts still require human review before sending; nothing is auto-sent.", ""]
    return "\n".join(lines)


def report_and_raise(out_dir: str | Path, tickets_path: str | Path, kb_path: str | Path, *,
                     include_optional: bool, log: Callable[[str], None] = print,
                     raise_on_failure: bool = True) -> list[Check]:
    """Run the checks, write validation_report.md, log a summary, and raise if a blocking check failed."""
    checks = run_checks(out_dir, tickets_path, kb_path, include_optional=include_optional)
    report = Path(out_dir) / VALIDATION_REPORT_FILE
    report.write_text(render_report(checks, tickets_path=tickets_path, kb_path=kb_path,
                                    include_optional=include_optional), encoding="utf-8")
    for c in checks:
        log(f"[validate] {_status(c):<4} {c.name}")
    failed = [c for c in checks if not c.passed and c.blocking]
    log(f"[validate] {sum(c.passed for c in checks)}/{len(checks)} checks passed -> {report}")
    if failed and raise_on_failure:
        raise ValidationFailed(f"{len(failed)} validation check(s) failed; see {report}")
    return checks
