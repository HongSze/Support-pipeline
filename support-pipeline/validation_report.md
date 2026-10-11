# Validation Report

- Generated: 2026-10-11T03:51:16+00:00
- Inputs: `tickets.json`, `kb_articles.json`
- Scope: full run (core outputs + optional analysis outputs)
- Result: **PASSED** — 17/17 checks passed

## Specification checks

| # | Check | Result | Details |
|---|---|---|---|
| 1 | Required artifacts exist | **PASS** | all 12 artifacts present |
| 2 | JSON files are valid | **PASS** | 11 JSON/JSONL files parsed |
| 3 | All tickets were processed | **PASS** | 12 tickets appear exactly once in each per-ticket output |
| 4 | Non-English / mixed-language tickets preserve original text and include English processing text | **PASS** | 2 non-English or mixed-language ticket(s) verified |
| 5 | Classified outputs use only controlled vocabularies | **PASS** | 12 classifications use allowed intent / urgency / sentiment values |
| 6 | Retrieval results reference valid article IDs from kb_articles.json | **PASS** | all retrieved articles exist in kb_articles.json (10 articles) |
| 7 | Each ticket has exactly 2 retrieved articles | **PASS** | 12 tickets x 2 articles |
| 8 | Priority scores are computed deterministically after retrieval | **PASS** | 12 scores match the formula, sorted descending, written after retrieval |
| 9 | Top 5 expedited tickets are selected from computed scores | **PASS** | expedited: T07, T01, T06, T09, T11 |
| 10 | Routing queues use only the controlled queue vocabulary | **PASS** | 12 routing decisions use allowed queues and safety labels |
| 11 | Reply drafts exist for all top 5 priority tickets | **PASS** | 5 drafts, one per expedited ticket |
| 12 | Reply drafts cite retrieved KB articles | **PASS** | every draft cites only articles retrieved for its ticket |
| 13 | LLM call logs contain separate records for required stages | **PASS** | 5 records; stages: multilingual_preprocessing, ticket_classification, queue_routing, reply_drafting, handoff_memory |

## Additional checks

| # | Check | Result | Details |
|---|---|---|---|
| 14 | Routing guardrails applied (required queues, minimum safety label) | **PASS** | required queues present and no safety label below the rule minimum |
| 15 | Reply drafts include channel and a human review gate note | **PASS** | every draft has the ticket's channel and a review gate note |
| 16 | Reply drafts pass safety rules (no promises, timelines, speculation, internal logic) | **PASS** | no safety-rule hits |
| 17 | Optional analysis outputs are well-formed | **PASS** | retrieval_quality.json, ops_summary.md and handoff_memory.json match their schemas |

All checks passed. Reply drafts still require human review before sending; nothing is auto-sent.
