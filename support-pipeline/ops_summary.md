# Ops Summary — Support Ticket Batch

- Tickets processed: **12**
- Expedited (top 5 by priority): T07, T01, T06, T09, T11
- Machine-translated: 2
- Weak or ambiguous retrieval: 0 (see retrieval_quality.json)

## Count by intent

| Intent | Tickets |
|---|---|
| withdrawal_issue | 1 |
| deposit_issue | 2 |
| login_access | 1 |
| verification_kyc | 2 |
| account_restriction | 2 |
| product_behavior | 1 |
| privacy_request | 1 |
| statement_export | 1 |
| api_support | 1 |

## Count by urgency

| Urgency | Tickets |
|---|---|
| critical | 1 |
| high | 5 |
| medium | 5 |
| low | 1 |

## Top recurring problem themes

Grouped by the help-center article each ticket matched best:

| Theme | Tickets | IDs |
|---|---|---|
| Account restriction and review communication (KB07) | 2 | T07, T11 |
| Deposit pending or missing after bank debit (KB03) | 2 | T06, T09 |
| API usage and rate limits (KB10) | 1 | T12 |
| Account access and session issues (KB04) | 1 | T02 |
| Additional verification checks (KB02) | 1 | T03 |

Recurring customer terms (number of tickets): account (7), after (3), document (3), last (3), need (3), request (3), bank (2), complaint (2), debit (2), deposit (2)

## Tickets with legal / regulatory risk

| Ticket | Queues | Safety label | Subject |
|---|---|---|---|
| T07 | Risk, Compliance, Payments | needs_legal_or_compliance_review | Formal complaint if funds remain blocked |
| T11 | Risk, Compliance, Payments | needs_legal_or_compliance_review | Please tell me exact reason for suspension |
| T03 | Compliance | needs_legal_or_compliance_review | Dokumen tambahan diminta |
| T05 | Privacy | needs_legal_or_compliance_review | Need account closure and data deletion |
| T10 | Compliance | needs_legal_or_compliance_review | Verification question |

## Tickets needing specialist handling

| Ticket | Intent | Queues | Safety label |
|---|---|---|---|
| T07 | account_restriction | Risk, Compliance, Payments | needs_legal_or_compliance_review |
| T01 | withdrawal_issue | Payments | needs_specialist_review |
| T06 | deposit_issue | Payments | needs_specialist_review |
| T09 | deposit_issue | Payments | needs_specialist_review |
| T11 | account_restriction | Risk, Compliance, Payments | needs_legal_or_compliance_review |
| T03 | verification_kyc | Compliance | needs_legal_or_compliance_review |
| T05 | privacy_request | Privacy | needs_legal_or_compliance_review |
| T10 | verification_kyc | Compliance | needs_legal_or_compliance_review |

## Expedited tickets (top 5 by priority score)

| Ticket | Score | Queues | Draft |
|---|---|---|---|
| T07 | 105 | Risk, Compliance, Payments | awaiting human review |
| T01 | 55 | Payments | awaiting human review |
| T06 | 55 | Payments | awaiting human review |
| T09 | 55 | Payments | awaiting human review |
| T11 | 55 | Risk, Compliance, Payments | awaiting human review |

_All reply drafts require human review before sending. Nothing is auto-sent._
