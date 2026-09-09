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
   - `receipt_id` is set to the literal string `'=ROW()-1'` (not a real ID); `raw_file_reference` and the receipt's real ID are swapped between columns; `status` is hardcoded to `'pending'` instead of `'pending_review'`.
   - Made `_next_id()` in `dashboard/data.py` and `api/sheets.py` tolerant of the malformed IDs so they don't crash on encountering them, but the underlying n8n fix is still needed.
   - A concise punch list for AA is written up in `epic_3_tickets.md`'s C3 section, including a "Get Row(s) → compute max + 1" fix for the ID (in plain English, no code, per request) rather than a timestamp-based ID.
3. **Credentials exposure (resolved):** a Google service-account JSON key was briefly committed to a local, unpushed commit. It's since been removed from HEAD (commit `c4542d7`). It was never pushed to `origin/main`, but the raw key still exists in the earlier local commit's history (`fbb9230`) unless that's been rewritten — rotating the key in Google Cloud Console is still worth doing as hygiene, even though it never left the local machine.
4. **No OpenAI API key access** — this is why the LLM call lives in n8n rather than Python. Options discussed: get the original key from whoever set up the "C25 OpenAI" n8n credential (not "read access" to n8n, since n8n stores credentials write-only — the raw key has to come from wherever it was first obtained), get a personal key (admin-justification message drafted earlier in this session), or use a different vendor entirely (the team's own docs allow "whatever LLM the team has credits for," naming Claude as an example).

## Session 2 (2026-09-09, later): Epic C code completed

Everything left on the DA side of Epic C is now built and tested. `pytest -q` —
**88 tests, green**, no credentials or network required.

### What was added

| File | What |
|---|---|
| `api/policy.py` | **New.** Handbook limits with the section and the date each figure was last set — Addendum B's 15% uplift applied where it applies (subsistence, staff entertainment) and deliberately not where it doesn't (client entertainment). Amara's live £250/£2,000 approval thresholds kept separate from the handbook's stale £1,000, so the gap is visible rather than silently resolved. |
| `api/audit.py` | **Rewritten.** The syntax break is gone. C4 proper: CPI lookup from FRED with the base period read per limit rather than a magic `255.0` constant, `contextual_validation()` classifying into WITHIN_LIMIT / GOOD_DEAL / OVER_GUIDELINE / POLICY_VIOLATION / NO_LIMIT, and `final_verdict()` mirroring n8n's "Final Risk Assessment" node. |
| `api/summary.py` | **New.** C5. One summary, two renderings (prose for the sheet and dashboard, mrkdwn for Slack) so the two surfaces cannot disagree. Deterministic flag codes translated to English; the governance prompt's own reasoning passed through verbatim. |
| `api/app.py` | **Rewritten.** `/api/audit` now runs C4 + C5 and writes both rows; added `/api/validate` (C4 alone, nothing persisted) and `/api/receipts/<id>` (C1's paper trail in one call); `/api/expenses` gained a `status` filter and page-size clamping. The sibling-import problem is fixed — it runs as `python api/app.py` and as `flask --app api.app run`. |
| `api/sheets.py` | Added `get_receipt` / `verdicts_for` / `decisions_for` / `audit_trail`, a **Benchmarks** tab for CPI provenance, and env-var overrides for the spreadsheet ID and key path. |
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
