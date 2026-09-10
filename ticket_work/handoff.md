# Handoff: Epic C — Intelligent Audit Engine session

Covers one working session on Epic C (C1, C3, C4, C5, C6). Companion doc: `ticket_work/epic_3_tickets.md` (the living ticket-by-ticket guide — this file is the narrative of how we got there and what's still open).

## What was asked for, and what shifted along the way

1. Started as a request for a click-by-click guide to the user's Epic C tickets (C1/C3/C4/C5/C6 — C2 is AA's, C7 is QA's).
2. Mid-session, the team dropped Postgres for a shared Google Sheet as the system of record (one-week timeline, easier than standing up an RDS). This meant rewriting the guide and the actual dashboard code, not just noting the change.
3. Building C3 (Policy Match) surfaced a real blocker: no OpenAI API key access. That led to two architecture pivots in sequence:
   - First: keep the LLM call in n8n (where AA already had a working OpenAI credential), have n8n POST the finished result to a new Flask API for persistence.
   - Then: realized `localhost:5000` isn't reachable from wherever n8n actually runs, and there's no hosting target for a standalone Flask server in this project (Streamlit Community Cloud is the only real hosting). Pivoted again to n8n's **native Google Sheets node** writing directly to the sheet — no custom API needs to be hosted anywhere for the live pipeline.
4. Partway through wiring that, discovered AA had *already* built their own Google Sheets persistence — but into a different, newly-added submission path (a Slack slash-command/modal flow), with several bugs. Guide was rewritten again to document reality and hand AA a fix list instead of duplicating the work.

## Deliverables (current state)

| File | Status | Notes |
|---|---|---|
| `ticket_work/epic_3_tickets.md` | Current, living doc | Full dependency/software/step-by-step per ticket. Rewritten twice for the architecture pivots above. |
| `dashboard/data.py` | Done, tested | Reads/writes the Google Sheet directly via `gspread` + `st.secrets`. Replaces the old `data/annotations.xml` mock loader. |
| `pages/1_Spend_Overview.py`, `pages/3_Expense_Browser.py` | Done, tested | Same data source swap, empty-sheet guards added. |
| `pages/2_Review_Queue.py` | Done, tested | Approve/Reject buttons now call `record_decision()` for real instead of being UI-only placeholders. |
| `streamlit_app.py`, `README.md` | Updated | Stale Postgres/mock-data references replaced with the Google Sheets setup flow. |
| `.streamlit/secrets.toml.example` | Added | Template for the service-account credentials Streamlit needs (`gcp_service_account` block + `spreadsheet_id`). |
| `api/governance_prompt.py` | Done | `SYSTEM_PROMPT` — starts from AA's existing n8n prompt text, extended with the concrete rules Amara confirmed (CFO $2,000 threshold, $250 line-manager band, 1-month cutoff, reasonableness test, non-listed-software sign-off, foreign-currency purchasing power, split-receipting caveat). Still needs PM sign-off — it's technically A3 content, unblocked here so C3 wasn't stalled. |
| `api/sheets.py` | Done, tested | `gspread` helpers: `_ensure_ws` (creates tabs/headers if missing), `insert_receipt`/`insert_verdict`, `_next_id` (now tolerant of malformed IDs). |
| `api/app.py` | Done, tested (mocked) | `/health`, `/api/expenses` (C6 — filterable/paginated query), `/api/audit` (C3 — persists a pre-computed verdict). Not wired into the live n8n pipeline by design (see pivot #3 above); kept as a tested local reference. |
| `api/audit.py` | Was broken here; rewritten in session 2 | The syntax break described below was real at the end of this session. See "Session 2" for what replaced it. |
| `requirements.txt`, `.gitignore` | Updated | Added `gspread`, `google-auth`, `openai`, `requests`, `python-dotenv`; removed `psycopg2` (no longer needed); gitignored credential files. |

## Ticket-by-ticket status

- **C1 (schema)** — done. Now expressed as 3 Google Sheet tabs (Receipts/Verdicts/Decisions) instead of 3 Postgres tables, same fields.
- **C6 (query API)** — code done and tested (`/api/expenses`), but not load-bearing: the dashboard reads the sheet directly, so this doesn't need to be hosted anywhere for the live system to work. Treat as satisfied-in-spirit.
- **C3 (Policy Match)** — governance prompt content done; Python persistence helpers done and tested standalone. **Blocked** on AA fixing their n8n Google Sheets integration (see below) — until that's fixed, no receipt from the real Slack upload path gets a stored verdict at all.
- **C4 (Contextual Validation)** — design done here, implementation broken at the end of this session; **built and tested in session 2** (see below).
- **C5 (High-risk routing/summary)** — summary generation and the dashboard rendering were built in session 2; still blocked end-to-end on C3's persistence gap closing (no verdict from the real Slack path gets saved yet, so Review Queue has nothing to show even for a real high-risk receipt).

## Known issues

1. ~~**`api/audit.py` has a syntax error right now** (line 28)~~ — **fixed in session 2**, the file was rewritten. Original note kept for the record: (line 28): `"api_key": ENV.,` — looks like an in-progress edit toward `ENV["FRED_API_KEY"]` or `ENV.get("FRED_API_KEY")` that got cut off. This breaks `api/app.py` on import (`from audit import map_verdict`) since Python won't import a file with a syntax error — **the whole Flask app currently fails to start.** Needs a one-line fix before anything else works.
2. **AA's n8n Google Sheets integration has real bugs** (full detail + fix list in `epic_3_tickets.md`'s C3 section):
   - Only covers a newly-added Slack slash-command/modal submission path, not the original file-upload path (B1/B4/B6) — the main demo flow currently has zero persistence.
   - Only high-risk items get saved; medium/low-risk receipts aren't persisted at all.
   - No Verdicts row is ever written anywhere — so even the one case that does save won't show up in Review Queue.
   - `receipt_id` is set to `'=ROW()-1'`. **Corrected later against the live sheet:** Sheets *evaluates* this as a formula, so the IDs look correct (3, 4, 5, 6) but are **positional** — deleting, inserting or sorting a row silently renumbers every receipt below it while the Verdicts and Decisions rows keep pointing at the old numbers. Quieter and more damaging than the inert-string failure originally assumed here. Also: `status` is hardcoded to `'pending'` instead of `'pending_review'`, and `raw_file_reference` carries the Slack file id while `receipt_id` should carry the computed number.
   - Made `_next_id()` in `dashboard/data.py` and `api/sheets.py` tolerant of the malformed IDs so they don't crash on encountering them, but the underlying n8n fix is still needed.
   - A concise punch list for AA is written up in `epic_3_tickets.md`'s C3 section, including a "Get Row(s) → compute max + 1" fix for the ID (in plain English, no code, per request) rather than a timestamp-based ID.
3. **Credentials exposure (resolved):** a Google service-account JSON key was briefly committed to a local, unpushed commit. It's since been removed from HEAD (commit `c4542d7`). It was never pushed to `origin/main`, but the raw key still exists in the earlier local commit's history (`fbb9230`) unless that's been rewritten — rotating the key in Google Cloud Console is still worth doing as hygiene, even though it never left the local machine.
4. **No OpenAI API key access** — this is why the LLM call lives in n8n rather than Python. Options discussed: get the original key from whoever set up the "C25 OpenAI" n8n credential (not "read access" to n8n, since n8n stores credentials write-only — the raw key has to come from wherever it was first obtained), get a personal key (admin-justification message drafted earlier in this session), or use a different vendor entirely (the team's own docs allow "whatever LLM the team has credits for," naming Claude as an example).

## Session 2 (2026-09-09, later): Epic C code completed

Everything left on the DA side of Epic C is now built and tested. `pytest -q` —
**104 tests, green**, no credentials or network required.

### What was added

| File | What |
|---|---|
| `api/policy.py` | **New.** Handbook limits with the section and the date each figure was last set — Addendum B's 15% uplift applied where it applies (subsistence, staff entertainment) and deliberately not where it doesn't (client entertainment). Amara's live £250/£2,000 approval thresholds kept separate from the handbook's stale £1,000, so the gap is visible rather than silently resolved. |
| `api/audit.py` | **Rewritten.** The syntax break is gone. C4 proper: CPI lookup from FRED with the base period read per limit rather than a magic `255.0` constant, `contextual_validation()` classifying into WITHIN_LIMIT / GOOD_DEAL / OVER_GUIDELINE / POLICY_VIOLATION / NO_LIMIT, and `final_verdict()` mirroring n8n's "Final Risk Assessment" node. |
| `api/summary.py` | **New.** C5. One summary, two renderings (prose for the sheet and dashboard, mrkdwn for Slack) so the two surfaces cannot disagree. Deterministic flag codes translated to English; the governance prompt's own reasoning passed through verbatim. |
| `api/app.py` | **Rewritten.** `/api/audit` now runs C4 + C5 and writes both rows; added `/api/validate` (C4 alone, nothing persisted) and `/api/receipts/<id>` (C1's paper trail in one call); `/api/expenses` gained a `status` filter and page-size clamping. The sibling-import problem is fixed — it runs as `python api/app.py` and as `flask --app api.app run`. |
| `api/sheets.py` | Added `get_receipt` / `verdicts_for` / `decisions_for` / `audit_trail`, a **Benchmarks** tab for CPI provenance (superseded in session 4 by the CPI tab), and env-var overrides for the spreadsheet ID and key path. |
| `dashboard/data.py` | Fixed two latent breakages: malformed `line_items` JSON took the whole page down, and the verdict merge cast IDs to a dtype that would not match cleanly. |
| `pages/2_Review_Queue.py` | Now shows the C5 summary (it previously showed only the bare verdict string), sorts high-risk first, takes an optional note into the audit trail, and says so explicitly when a verdict has no stored reasoning. |
| `tests/` | **New.** 88 tests across the audit engine, the policy limits, the summary, the API and the dashboard layer. FRED is stubbed and the sheet tabs are in-memory fakes, with an autouse guard that fails loudly if any test reaches the live spreadsheet. |
| `scripts/c4_demo.py` | **New.** C4's acceptance evidence, runnable: five constructed examples against live CPI, exits non-zero on a misclassification. Paste the output into MCP-27. |
| `.env.example`, `README.md`, `ticket_work/epic_3_tickets.md` | Documented all of the above. |

### Verified, not assumed

* **C4 ran live against FRED**, not only against mocks. CPIAUCSL 254.277 (2019-03) → 332.813 (2026-07). The headline example — an £88/head client dinner against a £75 limit that re-prices to £98.16 — classifies as `GOOD_DEAL`.
* The API's test payloads are copied out of the workflow export's node code, so the API cannot drift from what n8n actually holds without a test failing.
* `tests/test_schema_parity.py` pins `api/sheets.py`, `dashboard/data.py` and n8n's own column mapping to each other.

### Two bugs found and fixed along the way

* `dashboard/data.py` would raise on a malformed `line_items` cell, taking down every page that loads receipts. The sheet is hand-editable and n8n has already written at least one bad value, so this was a live risk, not a hypothetical.
* An early test run reached the **real** Google Sheet and hit a quota error, because `api/app.py` binds `receipts_ws` at import time and patching it on `api.sheets` alone missed it. Fixed, and `tests/conftest.py` now refuses live access outright so the same mistake fails loudly instead of silently.

### Still open, and honestly so

* **Currency is never converted.** The handbook is GBP, the sample data is USD. A non-GBP claim is still compared against the GBP limit, and the result carries `unconverted_currency: true` plus a sentence telling the reviewer to weigh the exchange rate and purchasing power themselves. Amara named both explicitly, so this is a real gap — it needs an FX source keyed on the transaction date (Handbook 12.2).
* **The CPI series is US** (`CPIAUCSL`). FRED's UK series stops in early 2025 and cannot answer a 2026 question. Overridable via `CPI_SERIES_ID`.
* **Attendee count is not in the schema**, so per-head limits divide by 1 unless a caller passes `attendee_count` — a shared dinner reads as an overage. One of the fields Mason already flagged as missing from B3.
* **AA's n8n punch list is unchanged** and still the thing blocking C3 and C5 end to end.
* **The governance prompt still needs PM sign-off** and still has not been pasted into the n8n node.

### Credential exposure — needs action

`.env`, containing the FRED API key, was committed in `c4542d7`. The service-account
JSON was committed earlier in `fbb9230`. **Neither commit has been pushed** —
`origin/main` is at `93e0c04` and local `main` is two commits ahead — so nothing has
left the machine. `.env` is now gitignored and untracked (staged as a deletion), but
that only stops future commits: both keys are still in those two local commits until
the history is rewritten. See "What you need to do" in the session summary.

## Session 3 (2026-09-09): verdicts collapsed from three tiers to two

The team dropped the middle tier. The pipeline is now three stages ending in a
two-way split, and **every receipt it processes ends in exactly one of them**:

    1. Deterministic policy checks  (hard limits, thresholds, one-month cutoff)
    2. Contextual validation (C4)   (category limit re-priced to today's CPI)
    3. Final risk assessment        (combine both with the governance prompt)
                                     -> low | high_risk

There are now two verdicts:

* **`low`** — the engine approves it outright. Status is written `approved`, a
  Decisions row is recorded against `ai_audit_engine`, and no human ever sees it.
* **`high_risk`** — status `pending_review`, goes to the CFO's review queue.

`compliant` → `low`, and `flagged` is gone.

**There is no third outcome and no parked state.** A receipt holding neither
verdict has not been through the pipeline — that is a failure to process it, not
a classification. Both dashboard pages now report it that way (a red error, not
an informational note), and `tests/test_audit.py` exhausts every combination of
policy checks, contextual audit and C4 assessment to prove no input can produce
anything but one of the two terminal states.

### Two decisions this forced that weren't specified

1. **n8n's MEDIUM maps to `high_risk`, not `low`.** MEDIUM was the "needs an
   explanation from the employee" tier. With no middle bucket it has to fold one
   way, and folding it down would auto-approve precisely the expenses the engine
   was not confident about. Same reasoning applies to an unrecognised risk level,
   which now defaults to `high_risk` rather than to the auto-approving value.
   n8n keeps emitting three risk levels — its three Slack replies still need the
   distinction — only the stored verdict collapses.
2. **`low` now changes state, not just labelling.** "Auto-approved" is
   meaningless unless the receipt actually becomes approved, so `/api/audit`
   writes `status = approved` *and* a Decisions row attributed to the engine. An
   approved receipt with no decision row would be an approval with nobody behind
   it — exactly the hole C1 exists to close.

### What changed

| File | Change |
|---|---|
| `api/policy.py` | New home for the verdict vocabulary: `VERDICT_LOW`, `VERDICT_HIGH`, `AUTO_DECIDER`, and `normalise_verdict()` for legacy rows. Imported by both the API and the dashboard so the two cannot drift. |
| `api/audit.py` | `RISK_TO_VERDICT` now maps HIGH **and MEDIUM** to `high_risk`; unknown levels default to `high_risk`. `final_verdict()` returns the two-value verdict while keeping n8n's three-value risk level. |
| `api/app.py` | `/api/audit` auto-approves on `low` — status plus a Decisions row — and returns `auto_approved` / `needs_review` so n8n can branch on it. |
| `api/sheets.py` | Added `insert_decision()`, used for the engine's own approvals. |
| `api/summary.py` | Two headlines. `low` reads "Auto-approved" and says review was not required, rather than the old "No action needed", which understated what had happened. |
| `dashboard/data.py` | Normalises legacy `compliant`/`flagged` on read, so the sheet needs no migration. |
| `pages/1`, `pages/2` | Review Queue filters on `high_risk` only and drops the two-tier sorting; Spend Overview's leakage metric follows. |
| `ticket_work/epic_3_tickets.md` | **The AA prompt was updated** — it carried the old three-way mapping and a hardcoded `pending_review`. Both would have written wrong data. |
| `tests/` | 104 tests. New coverage for the MEDIUM hazard, auto-approval status + decision row, legacy normalisation, and "unaudited is not low risk". |

### Migration

None needed. `normalise_verdict()` maps old rows on read: `compliant` → `low`,
`flagged` → **`high_risk`** (folding up, same reasoning as MEDIUM — it always
meant "a human needs to look at this"). The one live `compliant` row in the sheet
now reads as `low`. Rewriting the sheet's stored strings is optional tidying.

### Not changed, deliberately

`discovery_docs/` still uses the three-tier vocabulary — `tickets.md`'s
acceptance criteria say "compliant / flagged / high-risk", and
`data_schema_guide.md` lists the old status values. Those are shared team
artifacts and the ACs are the PM's; they need Alex's sign-off rather than a
silent edit. Flagged for the team, not rewritten here.

## Session 4 (2026-09-09): one global inflation series, no API key

Simplification decision: instead of a CPI source per country, C4 now uses a
single global series — the World Bank's world aggregate for annual
consumer-price inflation (`FP.CPI.TOTL.ZG`, country `WLD`) — applied to receipts
from anywhere.

**Why this is right, not just simpler.** What C4 re-prices is Meridian's own
firm-wide GBP limit, not the local price of the thing bought. A £75-a-head limit
is £75 a head whether the dinner was in Berlin or Bristol, so one inflation
number is the correct shape for the question. Per-country CPI was solving a
problem the design does not have.

**What it costs, and this is worth knowing before the demo.** The global series
is annual and published in arrears — latest full year 2025 — where a national
index like the UK ONS `D7BT` is monthly and current to 2026-07. So the
adjustment is year-granular, lags roughly a year, and under-states rather than
over-states. The brief asks for "2026 economic data"; this is 2025 data. Every
result reports the years it used, so it is visible rather than assumed.

**What it gains beyond simplicity:** no API key at all. `FRED_API_KEY` is gone
from the project, which is one fewer credential in a repo that has already had
two leaks.

### Numbers before and after

| Limit | was (US CPI) | now (global) |
|---|---|---|
| Client entertainment £75/head (2019) | £98.16 | £98.11 |
| Subsistence £46/day (2022) | £54.18 | £55.83 |

The C4 acceptance example is unaffected — an £88/head client dinner still
classifies `GOOD_DEAL` against the re-priced £98.11.

### Also checked and rejected

* **FRED's UK series** — all 40 UK CPI series on FRED are stale, freshest 2025-03,
  because FRED sources UK data from the OECD which stopped publishing them.
* **UK ONS `D7BT`** — monthly, current to 2026-07, no key. Genuinely the most
  accurate option for GBP limits, and rejected only because it reintroduces the
  per-country choice this change was made to remove. Worth reconsidering if
  recency is ever challenged.
* **IMF DataMapper** — would cover 2026 including projections, but returns 403 to
  this environment.

### The CPI data now lands in a sheet

n8n's agent tool sub-workflow reads a **CPI** tab instead of calling the World
Bank, so `scripts/sync_cpi.py` writes the series there: one row per year, with the
published rate and a chained price index anchored at 100. Re-pricing becomes
`index(B) / index(A)`, and a test asserts that division matches the engine's own
factor — otherwise the Slack reply and the dashboard could disagree about one
receipt.

`CPI_SPREADSHEET_ID` at the top of `api/sheets.py` is a **placeholder to fill in**
(unset = a CPI tab in the main spreadsheet). Whichever sheet it points at needs
the service account's `client_email` added as an Editor, or writes 403.

The per-verdict Benchmarks snapshot was removed — the full series in one place
supersedes it, and it was costing a Sheets round-trip on every audit.

Fallback rates are pinned at **full published precision**, not rounded: a 2dp
copy drifted about a penny per £100 of limit, which would have made the offline
demo and the live one disagree for no explicable reason.

## Immediate next steps, in order

Sessions 1 and 2 closed out everything that was DA-owned and codeable. What is
left needs either another person or a live system.

1. **Rewrite the two unpushed local commits** so neither credential ever ships (`fbb9230` has the service-account JSON, `c4542d7` has `.env`/the FRED key). Nothing has been pushed, so this is still entirely preventable. Rotate both keys afterwards regardless — cheap, and the FRED one takes a minute.
2. **Run the dashboard against the real sheet** — `streamlit run streamlit_app.py`. Nothing has been seen in a browser yet.
3. **Send AA the C3 punch list** from `epic_3_tickets.md`. It is unchanged and still the one thing blocking C3 and C5 end to end.
4. **Paste `api/governance_prompt.py`'s `SYSTEM_PROMPT` into n8n's "AI Contextual Audit" node.** Written, never handed over.
5. **Get PM sign-off on the governance prompt** (technically A3, drafted here to unblock C3).
6. **Once AA's fixes land**, re-test end to end with a real Slack file upload — the original path, not the slash-command one — and confirm rows land in both Receipts and Verdicts with a shared numeric `receipt_id`.
7. **Capture the C4 evidence** for MCP-27: `python scripts/c4_demo.py`, paste the output into the ticket.

## What's been tested vs. not

- **Tested (session 2):** 88 pytest tests over the audit engine, policy limits, summary generation, all API endpoints and the dashboard data layer — run on every change, all green. C4's CPI path additionally verified against a **live** FRED call, so the inflation figures are real rather than mocked. Test payloads for `/api/audit` are copied from the n8n workflow export's node code, so the API cannot drift from the workflow without failing.
- **Tested (session 1):** `dashboard/data.py` merge/decision/ID logic against mocked Sheets objects; a real gspread version mismatch (`.update()` argument order) caught before it shipped.
- **Not tested:** no live run against the actual Google Sheet (the test suite deliberately refuses to touch it), no OpenAI call from Python, nothing seen in a running Streamlit browser session, and no live n8n execution.
