# Epic C — The Intelligent Audit Engine: Ticket Guide

> **Architecture change (2026-09-09): Postgres → Google Sheets.**
> The team dropped Postgres in favor of a Google Sheet as the system of record for receipts, verdicts, and decisions — faster to stand up inside a one-week build, no local DB/RDS to provision, and every teammate can eyeball the data live. The sheet: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE/edit
>
> It already has three tabs — **Receipts**, **Verdicts**, **Decisions** — one per table from the original `database/setup.sql` design. They're currently empty (no header row yet); the setup steps below create the headers on first run. Every code sample in this guide reads/writes those three tabs via `gspread` instead of `psycopg2`/SQL. The `database/` folder (`setup.sql`, `seed.py`, `queries.sql`) is now legacy — left in the repo for reference, not used going forward.

## Big-picture findings (unchanged from the Postgres version of this guide)

1. **C1 is done** — schema now lives as the 3 sheet tabs below instead of 3 Postgres tables. Same fields, same intent.
2. **C3's real blocker (A3 Governance Prompt) doesn't exist as a finished artifact yet.** AA already built a working draft directly inside the n8n workflow — a generic "contextual reasonableness" system prompt plus two hardcoded rules (£2,000 CFO threshold, £250 line-manager threshold, 1-month cutoff). Real, usable v1 — just not the full handbook ruleset. Build on it rather than wait.
3. **C2 (CPI pull) hasn't been built at all** — no cron node, no CPI/FRED/BLS reference anywhere in n8n. It technically blocks C4; C4 now calls FRED directly and caches per process, and writes every observation it uses to a **Benchmarks** tab, which is both the workaround and the schema C2 should write into when AA builds it.
4. **AA's n8n workflow calls OpenAI directly** from the "AI Contextual Audit" node — not a DA-owned API. An orphaned "Store Expense Record" node pair is wired to nothing, so nothing persists anywhere right now. Revised plan (see C3, 2026-09-09): rather than repoint that node, DA supplies the real governance-prompt content for it and n8n forwards its finished result to a new Flask persistence endpoint — closes the same gap without needing DA to hold an OpenAI key.

Jira mapping: C1=MCP-21 (done), C3=MCP-25, C4=MCP-27, C5=MCP-31, C6=MCP-34. (C2 is AA's, C7 is Mason's.)

**Recommended order:** C6 → C3 → C4 → C5.

## Where each ticket stands (2026-09-09, end of DA build)

| Ticket | Code | Blocked on |
|---|---|---|
| C1 schema | Done — three sheet tabs, `tests/test_schema_parity.py` pins the API, the dashboard and n8n's column mapping to each other | — |
| C3 policy match | Done on the DA side: governance prompt, verdict logic, persistence, `POST /api/audit`, all tested | AA's n8n fixes (punch list below). No receipt from the real Slack upload path gets a stored verdict until those land. |
| C4 contextual validation | **Done** — built, tested against live FRED, acceptance evidence scripted | — (C2 worked around; see C4's "Standing in for C2") |
| C5 routing + summary | DA half done — summary generation, `/api/audit` response, Review Queue rendering | C3's persistence gap, then an end-to-end Slack run |
| C6 query API | Done — filters, pagination, `status` widening, audit-trail endpoint | — |

`pytest -q` — 88 tests, no credentials or network needed. Everything below marked
"done" is covered by them.

---

## One-time setup: Google Sheets access + the Flask "audit engine"

**Software:** Python 3, Flask, `gspread`, `google-auth`, a Google account with access to the sheet above.

### A. Create a service account (do this once — it's shared by the Flask API and the Streamlit dashboard)

1. Go to `console.cloud.google.com` → create a new project (or pick an existing one) → name it e.g. `expense-intelligence`.
2. In the left sidebar: **APIs & Services → Library** → search **Google Sheets API** → click it → **Enable**.
3. Repeat for **Google Drive API** → **Enable**.
4. **APIs & Services → Credentials** → **Create Credentials → Service Account** → name it `expense-audit-bot` → **Create and Continue** → skip role assignment → **Done**.
5. Click the new service account in the list → **Keys** tab → **Add Key → Create New Key → JSON** → downloads a `.json` file. Keep it safe, this is a credential.
6. Open the downloaded JSON, copy the `client_email` value (looks like `expense-audit-bot@expense-intelligence.iam.gserviceaccount.com`).
7. Open the Google Sheet link above → click **Share** (top right) → paste that service-account email → set role to **Editor** → **Send/Share**. (Do this even though the link is already "anyone with the link can edit" — API access needs the service account explicitly listed.)

### B. Wire the Flask app

8. In the repo root: `mkdir api && touch api/__init__.py`
9. Move the downloaded JSON key into the repo root as `service_account.json`.
10. Open `.gitignore`, add: `service_account.json` (never commit this file).
11. Open `requirements.txt`, add: `gspread`, `google-auth`, `openai`, `requests`.
12. `source .venv/bin/activate && pip install -r requirements.txt`
13. Create `api/sheets.py`:
    ```python
    import json
    from datetime import datetime, timezone

    import gspread
    from google.oauth2.service_account import Credentials

    SPREADSHEET_ID = "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]

    RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                        "category", "currency", "submitter", "raw_file_reference",
                        "status", "created_at", "updated_at"]  # payment_method/source_channel dropped from the sheet
    VERDICT_HEADERS = ["verdict_id", "receipt_id", "verdict", "reason", "created_at"]
    DECISION_HEADERS = ["decision_id", "receipt_id", "decision", "decided_by", "decided_at", "notes"]

    _client = None

    def client():
        global _client
        if _client is None:
            creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
            _client = gspread.authorize(creds)
        return _client

    def _ensure_ws(name, headers):
        ss = client().open_by_key(SPREADSHEET_ID)
        try:
            ws = ss.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
        if ws.row_values(1) != headers:
            ws.update(values=[headers], range_name="A1")  # gspread 6.x: values first, range_name second
        return ws

    def receipts_ws(): return _ensure_ws("Receipts", RECEIPT_HEADERS)
    def verdicts_ws(): return _ensure_ws("Verdicts", VERDICT_HEADERS)
    def decisions_ws(): return _ensure_ws("Decisions", DECISION_HEADERS)

    def _next_id(ws, id_col):
        records = ws.get_all_records()
        return max((int(r[id_col]) for r in records), default=0) + 1

    def insert_receipt(fields: dict) -> int:
        ws = receipts_ws()
        new_id = _next_id(ws, "receipt_id")
        now = datetime.now(timezone.utc).isoformat()
        row = {**{h: "" for h in RECEIPT_HEADERS}, **fields, "receipt_id": new_id,
               "status": fields.get("status", "pending_review"), "created_at": now, "updated_at": now,
               "line_items": json.dumps(fields.get("line_items", []))}
        ws.append_row([row[h] for h in RECEIPT_HEADERS], value_input_option="USER_ENTERED")
        return new_id

    def insert_verdict(receipt_id: int, verdict: str, reason: str) -> int:
        ws = verdicts_ws()
        new_id = _next_id(ws, "verdict_id")
        ws.append_row([new_id, receipt_id, verdict, reason, datetime.now(timezone.utc).isoformat()],
                      value_input_option="USER_ENTERED")
        return new_id
    ```
14. Create `api/app.py`:
    ```python
    from flask import Flask
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if __name__ == "__main__":
        app.run(port=5000, debug=True)
    ```
15. Run it: `python api/app.py` → visit `http://localhost:5000/health` → confirm `{"status":"ok"}`.

---

## C6 — Expose approved-expense query API (MCP-34)

> **Note on hosting:** this Flask endpoint has the same "only reachable from localhost" limitation as the original C3 plan — it's genuinely useful for local testing and as a demonstrable artifact, but isn't something that needs to be live for the actual dashboard to work: `dashboard/data.py` already reads the Google Sheet directly (no HTTP hop), which is how the dashboard stays fully functional on Streamlit Community Cloud without this API running anywhere. Treat `/api/expenses` as a satisfied-in-spirit deliverable (filterable, paginated query logic exists and is tested) rather than infrastructure the live system depends on.

**Dependencies:** C1 only (done). **Can start now: yes.**
**Software:** Flask app above, `gspread`, browser/curl.

1. Add to `api/app.py`:
   ```python
   from flask import request
   import pandas as pd
   from api.sheets import receipts_ws, RECEIPT_HEADERS

   @app.get("/api/expenses")
   def approved_expenses():
       page = int(request.args.get("page", 1))
       page_size = min(int(request.args.get("page_size", 25)), 100)

       df = pd.DataFrame(receipts_ws().get_all_records(), columns=RECEIPT_HEADERS)
       if df.empty:
           return {"total": 0, "page": page, "page_size": page_size, "results": []}

       df = df[df["status"] == "approved"]
       df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
       df["receipt_date"] = pd.to_datetime(df["receipt_date"], errors="coerce")

       if request.args.get("start_date"):
           df = df[df["receipt_date"] >= pd.Timestamp(request.args["start_date"])]
       if request.args.get("end_date"):
           df = df[df["receipt_date"] <= pd.Timestamp(request.args["end_date"])]
       if request.args.get("category"):
           df = df[df["category"] == request.args["category"]]
       if request.args.get("submitter"):
           df = df[df["submitter"] == request.args["submitter"]]
       if request.args.get("min_amount"):
           df = df[df["total_amount"] >= float(request.args["min_amount"])]
       if request.args.get("max_amount"):
           df = df[df["total_amount"] <= float(request.args["max_amount"])]

       total = len(df)
       start = (page - 1) * page_size
       page_df = df.iloc[start:start + page_size]
       return {"total": total, "page": page, "page_size": page_size,
               "results": page_df.assign(receipt_date=page_df["receipt_date"].dt.strftime("%Y-%m-%d")).to_dict("records")}
   ```
2. Restart Flask, test: `http://localhost:5000/api/expenses` — with the sheet still empty you'll get `{"total":0,...}`, which is correct. Add one test row to the **Receipts** tab by hand with `status=approved` to confirm filtering/pagination actually returns it.
3. Test a filter: `http://localhost:5000/api/expenses?category=travel&min_amount=50`.
4. Done once filters + pagination work against real sheet rows.

**Built beyond the snippet above** (all in `api/app.py`, covered by `tests/test_app.py`):

* `status=` widens the query past approved-only — `status=pending_review` for the queue, `status=all` for everything. QA needs that to sample verdicts for C7; the brief's "approved expenses queryable" stays the default.
* `page_size` is capped at 100 and floored at 1, and `page` at 1, so a bad query string returns a sane page rather than an exception or the whole sheet.
* `GET /api/receipts/<id>` returns the full paper trail for one receipt — the submission, every verdict against it in order, and every decision with who made it and when. That is C1's acceptance criterion as a single call, and it is what QA's D4 ticket walks to confirm nothing in the trail is missing or overwritten.

---

## C3 — Policy Match against Governance Prompt (MCP-25)

> **2026-09-09 revision (2nd) — AA already added a Sheets append node, but it doesn't close C3 yet.** AA replaced the workflow export with a new file, `discovery_docs/Expense - High Risk Google Sheets Append.json` (the old `Expense Intelligence - Receipt Intake.json` is gone). It's a bigger change than "add one node": AA added a whole new **manual-entry submission path** (a Slack slash-command → modal form → re-runs OCR/audit under new "2"-suffixed nodes) alongside the original file-upload path, and wired a Google Sheets "Append" node into that new path's high-risk branch only. Checked it node-by-node before writing anything further here — don't treat it as done, it has real gaps:
>
> - **The original Slack file-upload path — the one B1/B4/B6 actually describe, and presumably the main demo path — still has zero persistence.** Its own "High Risk?" node goes straight to a Slack message, same dead end as before. The new Sheets node only fires from the *new* modal-entry path.
> - **Only HIGH-risk modal submissions get saved.** Medium/low-risk ones aren't persisted at all — which breaks C6/E2/E5 (they need *every* receipt, not just the flagged ones).
> - **No verdict is ever written anywhere.** The Sheets node only appends to **Receipts** (13 columns match our schema exactly, good) — there's no matching write to **Verdicts**. So even the one case that does get saved won't show up in Review Queue, since that page filters on `verdict.isin(['flagged','high_risk'])` and no verdict row will exist for it.
> - **`receipt_id` is set to the literal string `'=ROW()-1'`** in the upstream "Prepare High-Risk Sheet Row" code node — not a real generated ID. Sheets will very likely store this as inert text, not evaluate it as a formula, meaning every row from this path gets the *same* non-numeric `receipt_id`. (I've made `_next_id()` in both `dashboard/data.py` and `api/sheets.py` tolerant of this — it now skips unparseable IDs instead of crashing — but the underlying value is still wrong/non-unique.)
> - **Column swap:** that same code node puts the expense's real original ID into `raw_file_reference` instead of `receipt_id`, and hardcodes `status` to `'pending'` (our schema/dashboard use `'pending_review'`).
>
> None of this is something I can fix from the Python/docs side — it needs a decision and a fix in the n8n workflow itself. What follows is the governance-prompt content (still correct and usable as-is) plus a concrete punch list to hand to AA. I have not assumed this is fixed in the steps below — I've marked exactly what still blocks C3 being genuinely done.

**Dependencies:** A3 content (workaround: reuse/extend AA's existing n8n system prompt — done, see step 1). AA fixing the persistence gaps above, or DA/AA agreeing on who does. **Can start now:** the prompt content and Python side, yes. **The actual "every receipt gets a stored verdict" acceptance criterion: no, blocked on the n8n fixes below.**
**Software:** `gspread`, n8n web UI (no OpenAI SDK/key needed in Python — see the earlier revision above for why).

1. `api/governance_prompt.py` — done. `SYSTEM_PROMPT` starts from AA's existing "AI Contextual Audit" node prompt and extends it with the concrete rules Amara actually confirmed (CFO threshold $2,000, line-manager band $250–$2,000,
1-month cutoff no exceptions, the reasonableness test, non-listed-software sign-off, foreign-currency purchasing power, split-receipting). Sync with PM before calling this final — it's technically A3 content. Paste it into the "AI Contextual Audit" node's `jsonBody` → `input[0].content[0].text` (plain text inside the existing backtick template literal — the prompt has no backticks or `${...}` in it, so it's safe to paste with real line breaks).
2. Send AA this punch list:
   - **Run on both branches, all risk tiers.** Move the Sheets append upstream of the High/Medium/Low check (or replicate it on the original file-upload branch too) — right now only high-risk modal submissions get saved.
   - **Fix `receipt_id`:** before "Prepare High-Risk Sheet Row", add a Google Sheets **Get Row(s)** node reading the Receipts tab. In "Prepare High-Risk Sheet Row", replace `'=ROW()-1'` with the highest existing `receipt_id` from that Get Row(s) output plus one (falling back to 1 if the sheet's empty), instead of a hardcoded formula string.
   - **Fix the swap:** `raw_file_reference` = the actual file reference; `receipt_id` = the computed value above (not the reverse).
   - **Fix status:** `'pending'` → `'pending_review'`.
   - **Add a Verdicts append** (Google Sheets, Append, sheet = Verdicts) right after the Receipts append: `verdict_id` = any unique value, `receipt_id` = the same id just written, `verdict` = `{{ {HIGH:'high_risk', MEDIUM:'flagged', LOW:'compliant'}[$json.final_audit_result.risk_level] }}`, `reason` = `{{ $json.final_audit_result.contextual_summary }}`, `created_at` = `{{ $now.toISO() }}`.
3. Once AA applies those fixes (or you do, if you have edit access — same instructions apply either way), test with a real Slack upload of a receipt image (the original path, not the slash-command/modal one) and confirm a row lands in **both** Receipts and Verdicts, with a real numeric `receipt_id` shared between them, `status = pending_review`, and `raw_file_reference` pointing at the actual file.
4. Done once that's true for all three risk tiers, not just high-risk — that's what actually satisfies "every ingested receipt receives a stored policy verdict."

### The DA side of C3, as built

`POST /api/audit` is complete and tested end to end against mocked sheets. It:

* accepts **either** payload shape n8n could send — the nested one the workflow carries internally (`audit_engine_input` / `contextual_audit` / `final_audit_result`), or the flat one an HTTP node placed after "Final Risk Assessment" would post. The test payloads in `tests/test_app.py` are copied from the node code in the workflow export, not invented, so the API cannot quietly drift from what n8n actually holds;
* **trusts n8n's `risk_level` when it sends one** — n8n has already run the governance prompt, and the API must not disagree with the verdict the submitter was told in Slack. When no risk level is supplied, `final_verdict()` recomputes it from the deterministic checks plus the contextual audit. That function is a deliberate line-by-line mirror of n8n's "Final Risk Assessment" node, which makes it the executable spec QA can check that node against for C7;
* runs C4 and folds the result into the stored reason, and generates the C5 summary;
* writes **both** rows — Receipts *and* Verdicts — with a real incrementing numeric `receipt_id` shared between them and `status = 'pending_review'`. That is precisely the set of things AA's current Sheets node gets wrong, so if the punch list below stalls, pointing n8n at this endpoint behind a tunnel fixes all of them at once.

None of that changes the blocker: as long as the live pipeline writes to the sheet through n8n's own node, the punch list above is what has to land.

<details>
<summary>Alternative: Python-side LLM call (needs an OpenAI/Anthropic key) — kept for reference, not the current path</summary>

If a key becomes available later and the team prefers DA's API to make the LLM call directly instead of n8n:

```python
# api/audit.py
import os, json
from openai import OpenAI
from governance_prompt import SYSTEM_PROMPT

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client

SCHEMA = { ... }  # same 9-field schema as the n8n node — see governance_prompt.py's docstring

def run_contextual_audit(audit_reasoning_input: dict) -> dict:
    resp = _get_client().responses.create(
        model="gpt-5",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Assess this expense:\n\n{json.dumps(audit_reasoning_input, indent=2)}"},
        ],
        text={"format": {"type": "json_schema", "name": "expense_contextual_audit", "strict": True, "schema": SCHEMA}},
    )
    return json.loads(resp.output_text)

def final_verdict(policy_checks: dict, audit: dict) -> tuple[str, str]:
    high = (policy_checks.get("human_review_required")
            or "CFO_APPROVAL" in policy_checks.get("approvals_required", [])
            or audit["recommended_action"] == "NEEDS_HUMAN_REVIEW"
            or audit["business_relevance"] == "LIKELY_PERSONAL"
            or audit["reasonableness"] == "UNREASONABLE")
    if high:
        return "high_risk", "HIGH"
    medium = (audit["recommended_action"] == "NEEDS_EMPLOYEE_EXPLANATION"
              or audit["business_relevance"] == "UNCLEAR"
              or audit["reasonableness"] in ("QUESTIONABLE", "INSUFFICIENT_INFORMATION")
              or audit["confidence"] < 0.75)
    return ("flagged", "MEDIUM") if medium else ("compliant", "LOW")
```

Then `/api/audit` would call `run_contextual_audit(payload)` itself instead of trusting a pre-computed `risk_level`, and n8n's "AI Contextual Audit" node would be repointed at this Flask endpoint instead of OpenAI directly (URL swap + simplified body, and simplify "Parse Audit Result" to read the flat response instead of walking OpenAI's envelope).
</details>

---

## C4 — Contextual Validation, inflation-aware (MCP-27)

> **Status (2026-09-09): built and tested.** `api/policy.py`, `api/audit.py`,
> `POST /api/validate`, `scripts/c4_demo.py`, and 30 tests in
> `tests/test_audit.py` + `tests/test_policy.py`. Verified against a live FRED
> call, not just mocks.

**Dependencies:** C2's benchmark data (still not built) — worked around, see below. **Can start now: done.**
**Software:** free FRED API key, `requests`, `python-dotenv`.

### What it does

Every limit in `api/policy.py` carries the period it was last set in, traced to a
handbook section or an addendum. `api/audit.py` re-prices that limit to today's
CPI before comparing it to the receipt:

```
adjusted_limit = static_limit x (CPI_now / CPI_when_the_limit_was_written)
```

and classifies the claim as one of:

| Assessment | Meaning |
|---|---|
| `WITHIN_LIMIT` | Inside the figure as written — no argument either way |
| `GOOD_DEAL` | Over the stale figure, inside the re-priced one. **This is the ticket's whole point, and it does not raise a flag.** |
| `OVER_GUIDELINE` | Over the re-priced figure, but Section 5.2 calls that figure a guideline, not a ceiling → flagged for explanation |
| `POLICY_VIOLATION` | Over the re-priced figure on a hard limit → high risk |
| `NO_LIMIT` | No numeric ceiling for this category; the general approval thresholds govern |

The outcome is folded into the verdict's `reason` text rather than becoming a
fourth verdict value — verdicts stay `compliant` / `flagged` / `high_risk`.

### Where the numbers came from

| Category | Limit | Set | Source |
|---|---|---|---|
| Subsistence | £46.00 / day | 2022-01 | 3.1 (£40) uplifted 15% by Addendum B |
| Client entertainment | £75.00 / head | 2019-03 | 5.2 — a *guideline*; Addendum B deliberately skipped it, so it is the stalest live figure in the book |
| Staff entertainment | £46.00 / head | 2022-01 | 6.2 (£40) uplifted 15% by Addendum B |
| Software / subscriptions | £50.00 / month | 2019-03 | 7.1 (pre-approved list only — 7.2 needs manager + IT sign-off regardless of cost, which no limit check can clear) |
| Travel, accommodation, training, office supplies, postage, misc | none | — | Governed by the approval thresholds instead |

Approval thresholds (£250 line manager, £2,000 CFO) are Amara's live figures, not
handbook ones, so they are deliberately *not* inflation-adjusted. n8n's
"Deterministic Policy Checks" node is what enforces them.

### Setup

1. Get a FRED key: `fred.stlouisfed.org` → **My Account** → **API Keys** → **Request API Key**. Free and instant.
2. `cp .env.example .env` and paste the key in as `FRED_API_KEY`.
3. `pytest -q` — 88 tests, no credentials or network needed.
4. `python scripts/c4_demo.py` — runs five constructed examples against live CPI.

### Acceptance evidence

The AC asks for "a receipt priced above a static old limit but within current
inflation-adjusted benchmark [...] correctly classified as acceptable (and vice
versa) — demonstrated with at least one constructed example."

The headline example: **an £88-per-head client dinner.** The handbook says £75
(Section 5.2, March 2019, never uplifted). CPI has moved 254.277 → 332.813 over
that period, so £75 in 2019 money is **£98.16** today. £88 is over the written
figure and comfortably under the re-priced one → `GOOD_DEAL`, not a flag.

And the reverse: **£60 a day of subsistence.** The limit is £46/day (2022-01),
re-priced to £54.18 → `POLICY_VIOLATION`, over the limit on both the old figure
and the current one.

Both are asserted in `tests/test_audit.py::test_c4_acceptance_criterion_constructed_example`
and printed with their CPI provenance by `scripts/c4_demo.py`. Paste that script's
output into MCP-27 — it is the artifact, and it exits non-zero if anything
misclassifies.

### Standing in for C2

C2 (AA's scheduled CPI pull) still does not exist. `cpi_for()` calls FRED
directly and caches per process, which is what the cron job would have provided.
Two things make this safe to hand over:

* Every CPI observation actually used gets written to a **Benchmarks** tab
  (`series_id`, `period`, `value`, `fetched_at`, `source`), once per process, so
  any past verdict can be re-checked against the index level it was decided on.
  That tab is the shape C2 should write when AA builds it.
* When C2 lands, point `cpi_for()` at the Benchmarks tab instead of FRED.
  Nothing else in the module changes.

### Known gaps, stated rather than hidden

* **Currency is not converted.** The handbook is GBP; the sample data is USD. A
  non-GBP claim is still compared against the GBP limit, and the result carries
  `unconverted_currency: true` plus a sentence in the reason telling the reviewer
  to weigh the exchange rate and local purchasing power themselves. Amara called
  both out explicitly, so this is a real gap — closing it needs an FX rate source
  keyed on the transaction date (Handbook 12.2).
* **The CPI series is US (`CPIAUCSL`).** FRED's UK series (`GBRCPIALLMINMEI`)
  stops in early 2025, which cannot answer a 2026 question. Override with
  `CPI_SERIES_ID` if a better current UK series turns up.
* **Attendee count is not captured.** Per-head limits therefore divide by 1
  unless a caller passes `attendee_count`, so a shared dinner reads as an
  overage. This is one of the schema fields Mason flagged as missing; until B3
  captures it, a per-head overage means "ask", not "reject".

---

## C5 — High-Risk routing & natural-language summary (MCP-31)

> **Status (2026-09-09): the DA half is built and tested.** `api/summary.py`,
> wired into `POST /api/audit`, surfaced in `pages/2_Review_Queue.py`, covered by
> `tests/test_summary.py`. What remains is AA-side delivery and an end-to-end run.

**Dependencies:** C3's persistence gap (the punch list above) must close before a real receipt can travel this path end to end.
**Software:** n8n web UI, Slack, Streamlit.

### What it does

`build_summary()` produces one summary in two renderings from the same facts, so
the sentence Amara reads in Slack and the one she reads in the dashboard cannot
disagree:

* `summary` — prose, stored in the Verdicts tab's `reason` column and rendered in
  Review Queue.
* `slack_message` — the same content in Slack mrkdwn, returned by `/api/audit` so
  n8n's Slack node can post it verbatim.

It leads with the four things the AC names — what was flagged, why, the amount,
the submitter — because Amara's bar is "a lot of the time, it can just be a
sentence". Deterministic flag codes are translated into English
(`EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF` → "submitted more than a month after the
expense date, which policy auto-rejects with no exceptions"); the governance
prompt's own free-text reasoning passes through verbatim; C4's assessment is
appended. No second LLM call — the reasoning already exists upstream, and
regenerating it would add latency, cost, and another thing that can hallucinate.

Example output for a high-risk client dinner:

> **Needs your decision**: £264.00 at The Ivy (client entertainment), submitted
> by U04ALEX, dated 2026-08-14. Client dinner for three during the Rowan
> engagement. Flagged because it is at or above the £2,000 CFO approval
> threshold; and £264.00 per head is over £98.16 per head — the handbook's
> £75.00 per head restated in today's money (prices are up 30.9% since 2019-03).

### Dashboard half — done

`pages/2_Review_Queue.py` now shows the summary under each receipt (it previously
showed only the bare verdict string), sorts high-risk above flagged so Amara's own
queue is on top, takes an optional note that is recorded in the audit trail, and
says so explicitly when a verdict has no stored reasoning rather than rendering a
blank card.

### Slack half — still on AA

1. Confirm **"High-Risk Expense Slack Routing"**, **"Request Employee Explanation"** and **"Low Risk Compliance Feedback"** still reference `$json.final_audit_result.contextual_summary`. Untouched by anything here, so they should still work.
2. If the workflow is ever pointed at `/api/audit`, use the response's `slack_message` field directly instead of re-formatting in the node — that is what keeps the two surfaces identical.
3. Submit a real test receipt through Slack; confirm the reply's merchant, amount and reason match the Verdicts row.

### Done when

A high-risk test receipt produces a Slack message *and* a Verdicts row, the
Review Queue shows that same text, and `/api/expenses` can pull the receipt back
out. Steps 1-2 of the C3 punch list have to land first.
