# Support-Ops Pipeline

A staged pipeline that does the following, in order:

1. Ingests support tickets from disk.
2. Normalises multilingual input.
3. Classifies intent and urgency.
4. Retrieves help-center guidance.
5. Scores priority deterministically.
6. Routes tickets to internal queues.
7. Drafts safe replies behind human-review gates.

Python 3.10+, standard library only. No API key or external model is needed: LLM steps use a deterministic simulated model (`support_pipeline/simulated_model.py`). Prompts are still built in full and every call is logged, so a real model can replace `SimulatedModel.generate` in `llm.py` without changing anything else.

## Commands

```bash
python run_pipeline.py      # or: make run       — runs every stage, regenerates all artifacts
python validate.py          # or: make validate  — checks the artifacts, writes validation_report.md
make all                    # run + validate
make clean                  # delete generated artifacts
```

The pipeline reads `tickets.json` and `kb_articles.json` fresh on every run, so replacing them with other data in the same schema just works. Nothing is precomputed.

## Artifacts (written to the repo root)

| File | Spec |
|---|---|
| `tickets.json`, `kb_articles.json` | Inputs |
| `preprocessed_tickets.json` | 1. Multilingual preprocessing |
| `classified_tickets.json` | 2. Ticket classification (Stage 1 LLM call) |
| `retrieval_results.json` | 3. Knowledge retrieval, top 2 per ticket |
| `priority_scores.json` | 4. Deterministic priority scoring, sorted, top 5 `expedited` |
| `routing_decisions.json` | 5. Queue routing (Stage 2 LLM call) |
| `reply_drafts.json` | 6. Reply drafts for the top 5 (Stage 3 LLM call) |
| `retrieval_quality.json` | 7. Retrieval quality notes |
| `ops_summary.md` | 8. Batch summary for operations |
| `handoff_memory.json` | 9. Conversation memory seed (LLM call) |
| `validation_report.md` | 10. Validation report |
| `llm_calls.jsonl` | One record per LLM call |

## Stages

The state machine is enforced in `pipeline.py`: a stage runs only from its required state and may only advance one step. Each stage is its own module in `support_pipeline/stages/` and reads earlier artifacts from disk.

```
INIT -> TICKETS_LOADED -> PREPROCESSING_COMPLETE -> TICKETS_CLASSIFIED -> KB_RETRIEVAL_COMPLETE
     -> PRIORITY_SCORES_COMPUTED -> ROUTING_COMPLETE -> REPLY_DRAFTS_GENERATED
     -> VALIDATION_COMPLETE -> RESULTS_FINALISED
```

## LLM call log

`llm_calls.jsonl` has one JSON object per call, including retries. Each record contains `stage`, `timestamp` (ISO-8601), `provider`, `model`, `prompt_hash`, `input_artifacts` and `output_artifact`, plus `task`, `attempt`, `valid` and `validation_errors`.

| Stage name in log | Output artifact |
|---|---|
| `multilingual_preprocessing` (only when a ticket needs translation) | `preprocessed_tickets.json` |
| `ticket_classification` | `classified_tickets.json` |
| `queue_routing` | `routing_decisions.json` |
| `reply_drafting` | `reply_drafts.json` |
| `handoff_memory` | `handoff_memory.json` |

Retrieval and priority scoring are pure deterministic code, so they make no LLM calls.

## Validation

All checks live in `support_pipeline/checks.py` and read the artifacts back from disk. Three places use them:
- The pipeline's validation stage checks the core outputs and stops the run on failure.
- The finalise stage re-runs the full set once the optional outputs exist.
- `python validate.py` runs the full set standalone.

Each writes `validation_report.md`.

**Specification checks:**
1. Required artifacts exist
2. JSON files are valid
3. All tickets were processed (exactly once in each per-ticket output)
4. Non-English or mixed-language tickets preserve original text and include English processing text
5. Classified outputs use only controlled vocabularies
6. Retrieval results reference valid article IDs (and titles) from `kb_articles.json`
7. Each ticket has exactly 2 retrieved articles
8. Priority scores match the formula, are sorted, and were written after retrieval
9. The top 5 expedited tickets match a fresh ranking of the recomputed scores
10. Routing uses only the controlled queue and safety-label vocabularies
11. Reply drafts exist for all top 5 priority tickets (and only those)
12. Reply drafts cite only that ticket's retrieved KB articles
13. The LLM log has records with all required fields for every required stage

**Additional checks:**
- Routing guardrails were applied.
- Each draft has its channel and a review gate note.
- Optional outputs are well-formed.
- Reply-safety rules pass. This one is a warning only: a hit means the reviewer must rewrite the draft.

## Key rules

**Controlled vocabularies.** These are defined in `config.py` and listed in every prompt. Model output is checked by exact membership. An invalid batch is retried once with the errors fed back. Any ticket still invalid gets a safe fallback.

**Retrieval.** BM25 over `kb_articles.json` only, with no hardcoded mappings. The query is the English ticket text plus the classified intent's words. Scores are mapped to 0–1 by `bm25 / (bm25 + 4)`.

**Priority.** This is the spec formula, in code (`policy.compute_priority`):

| Component | Points |
|---|---|
| Base (urgency) | critical 40, high 25, medium 10, low 3 |
| Customer tier | VIP 10, standard 0 |
| `mentions_funds_blocked` | 20 |
| `mentions_regulator_or_legal_threat` | 25 |
| `requires_specialist_handling` | 10 |
| Top retrieval score < 0.55 | 8 |

Ties are broken by `created_at` (older first), then `ticket_id`.

**Routing guardrails.** If the model omits them, code adds the required queues:
- regulator threat → Compliance
- funds blocked → Payments
- privacy → Privacy
- KYC → Compliance
- restriction → Risk

The safety label can be raised to the rule-based minimum, never lowered.

**Drafts.** Reply-safety rules run inside the drafting retry loop. They block:
- promises, guarantees or timelines
- speculation
- disclosing internal logic, or giving legal advice
- requests for credentials, or echoing personal data
- citing articles that weren't retrieved for that ticket

Nothing is auto-sent.

## Tuning

These `config.py` constants are untuned:
- `SCORE_SATURATION` (4.0) sets how spread out retrieval scores are relative to the 0.55 weakness threshold.
- `AMBIGUITY_MARGIN` (0.05) sets how close the top two articles must be to count as ambiguous.
