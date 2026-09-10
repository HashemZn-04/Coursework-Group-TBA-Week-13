# Data Schema Guide (Ticket B3)

Your step-by-step for defining the shared receipt schema today.

1. **List the fields** every downstream piece needs: merchant, date, line items, tax, total, currency, submitter, source channel, raw file reference.
2. **Add IDs/metadata** needed for tracking: receipt ID, submission timestamp, status (e.g. `pending_review`).
3. **Structure line items as an array** of `{description, amount, quantity}` — don't flatten them.
4. **Pick concrete types** for every field (date → ISO 8601, amounts → decimal, currency → ISO code) so there's no ambiguity later.
5. **Write it as a single example JSON object** — faster to react to than a spec doc.
6. **Send it to AA before the kickoff** — confirm OCR can realistically populate every field you listed.
7. **Send it to QA before the kickoff** — confirm every field is verifiable/testable.
8. **Present at the whole-team kickoff, get explicit sign-off from all 4 roles, lock it.**
9. **Any change after lock goes through PM** and gets re-broadcast to the whole team immediately.

## Reference: minimum field set

| Field | Type | Notes |
|---|---|---|
| `receipt_id` | string | unique per submission |
| `submitted_at` | ISO 8601 datetime | |
| `submitter` | string | Slack user / email |
| `source_channel` | string | `slack` \| `email` |
| `merchant` | string | |
| `date` | ISO 8601 date | date on the receipt, not submission date |
| `line_items` | array of `{description, amount, quantity}` | |
| `tax` | decimal | |
| `total` | decimal | |
| `currency` | string | ISO 4217 code |
| `raw_file_ref` | string | pointer/URL to the original image or PDF |
| `status` | string | `pending_review` \| `approved` \| `rejected` |
| `verdict` | string | `low_risk` \| `high_risk` — the risk assignment outcome, set at processing time |
| `verdict_reason` | string | free-text reasoning behind the verdict |
| `decided_at` | ISO 8601 datetime | blank until the CFO acts on a `high_risk` receipt |

Note: the live Google Sheet is now a single Receipts table — there is no
separate Verdicts/Decisions tab. `verdict`, `verdict_reason` and `decided_at`
are columns on the same row as everything else above.
