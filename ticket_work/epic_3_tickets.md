# Epic C — The Intelligent Audit Engine: Ticket Guide

> **Architecture change (2026-09-09): Postgres → Google Sheets.**
> The team dropped Postgres in favor of a Google Sheet as the system of record for receipts, verdicts, and decisions — faster to stand up inside a one-week build, no local DB/RDS to provision, and every teammate can eyeball the data live. The sheet: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE/edit
>
> It already has three tabs — **Receipts**, **Verdicts**, **Decisions** — one per table from the original `database/setup.sql` design. They're currently empty (no header row yet); the setup steps below create the headers on first run. Every code sample in this guide reads/writes those three tabs via `gspread` instead of `psycopg2`/SQL. The `database/` folder (`setup.sql`, `seed.py`, `queries.sql`) is now legacy — left in the repo for reference, not used going forward.

## Big-picture findings (unchanged from the Postgres version of this guide)

1. **C1 is done** — schema now lives as the 3 sheet tabs below instead of 3 Postgres tables. Same fields, same intent.
2. **C3's real blocker (A3 Governance Prompt) doesn't exist as a finished artifact yet.** AA already built a working draft directly inside the n8n workflow — a generic "contextual reasonableness" system prompt plus two hardcoded rules (£2,000 CFO threshold, £250 line-manager threshold, 1-month cutoff). Real, usable v1 — just not the full handbook ruleset. Build on it rather than wait.
3. **C2 (CPI pull) hasn't been built at all** — no cron node, no CPI reference anywhere in n8n. It technically blocks C4; `scripts/sync_cpi.py` stands in by writing the World Bank's global series to a **CPI** tab that n8n's agent reads, which is both the workaround and the exact job C2 should automate on a schedule.
4. **AA's n8n workflow calls OpenAI directly** from the "AI Contextual Audit" node — not a DA-owned API. That stays as it is: the team's OpenAI credential lives in n8n, DA has no key, and there is nowhere to host a Flask app anyway. DA's job on C3 is therefore the *content* of that node's prompt plus the persistence schema, not the LLM call. Partial persistence now exists (one branch of one path); what is still missing, and why it matters, is in the C3 section below.

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

`pytest -q` — 100 tests, no credentials or network needed. Everything below marked
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

**Dependencies:** A3's rule content (worked around — AA's existing n8n system prompt was extended rather than waited on, see step 1). Then AA closing the persistence gaps below.
**Can start now:** the prompt content and the Python side — both done. **The actual "every ingested receipt receives a stored policy verdict" criterion: no, blocked on the n8n fixes below.**
**Software:** n8n web UI, `gspread`. No OpenAI SDK or key needed in Python — the LLM call stays in n8n, where the team's credential already lives.

### Step 1 — paste the governance prompt into n8n (DA task, not yet done)

`api/governance_prompt.py`'s `SYSTEM_PROMPT` is written and ready. It starts from
AA's existing "AI Contextual Audit" node prompt and extends it with the rules
Amara actually confirmed: the $2,000 CFO threshold, the $250 line-manager band,
the one-month cutoff with no exceptions, the reasonableness test, non-listed
software needing manager + IT sign-off, foreign-currency purchasing power, and
the split-receipting caveat.

Paste it into the "AI Contextual Audit" node's `jsonBody` →
`input[0].content[0].text`, replacing the text inside the existing backtick
template literal. The prompt contains no backticks and no `${...}`, so it is safe
to paste with real line breaks. Do this on **both** copies of the node — the
unsuffixed one and "AI Contextual Audit2" — or the two paths will judge the same
receipt by different rules.

Sync with Alex before calling this final: it is technically A3 content, drafted
here so C3 wasn't stalled waiting on it.

### Step 2 — for AA: what's wrong, why it matters, and a prompt to fix it

AA replaced the workflow export with `discovery_docs/Expense - High Risk Google Sheets Append.json`
and added a Google Sheets "Append" node. That was real progress, but C3 is not
closed yet. Checked node-by-node against the live sheet on 2026-09-09.

**The one-line version for AA:** five of the six receipts in the sheet right now
have no verdict stored anywhere, so the CFO's Review Queue is empty and the
approve/reject demo has nothing to act on. The fix is entirely inside the n8n
workflow.

#### What's wrong, and what each one actually breaks

| # | What the workflow does now | Why that breaks something |
|---|---|---|
| 1 | The Sheets append is wired **only into the modal/slash-command path** ("2"-suffixed nodes). The original Slack **file-upload** path ends at a Slack message. | The file-upload path is the one B1/B4/B6 describe and the one we demo. Every receipt submitted the normal way is currently **thrown away** after the Slack reply. |
| 2 | The append sits on the **high-risk branch only** (`High Risk?2` → true). | Medium and low risk receipts are never saved. The dashboard's spend totals, category breakdown and "all approved expenses queryable" (C6) need *every* receipt. This matters more now that low risk is auto-approved: an auto-approved receipt that was never written down is an approval with no record of it at all. |
| 3 | **Nothing is ever written to the Verdicts tab.** Only Receipts is appended to. | This is the one that empties the Review Queue. That page filters on `verdict = 'high_risk'`, and the verdict lives in the Verdicts tab. No verdict row = the receipt is invisible to the CFO, no matter how risky it was. It also means C3's own acceptance criterion — "every ingested receipt receives a stored policy verdict" — is unmet by definition. |
| 4 | `receipt_id` is set to the string `'=ROW()-1'` in "Prepare High-Risk Sheet Row". | Confirmed on the live sheet: Sheets **evaluates** this as a formula, so the IDs *look* right (3, 4, 5, 6…). The problem is they are **positional, not stable**. Delete, insert or sort a row and every ID below it silently changes — while the Verdicts and Decisions rows keep pointing at the old numbers. The audit trail then attributes decisions to the wrong receipts, with no error anywhere. C1's whole acceptance criterion is "for any receipt, reconstruct what was submitted, what the AI decided, and what the human did" — a renumbering ID makes that impossible to trust. |
| 5 | `status` is hardcoded to `'pending'`. | The schema and every dashboard filter use `'pending_review'`. `'pending'` matches nothing, so those rows fall out of the status filters. |

Not a bug, checked and cleared: the 13 Receipts columns map correctly, and
`category` populates fine (`Audit Engine Input2` includes `submission`, unlike its
twin on the other path).

#### The prompt to give an LLM

AA can paste this straight into whatever assistant they use, along with the
workflow JSON export. It is written to be self-contained — it does not assume the
assistant has seen this repo.

---

```
I have an n8n workflow that processes employee expense receipts. I'm attaching
the workflow JSON export. I need you to make five changes to it. Please give me
the exact node configuration and code for each, and tell me precisely where each
node goes in the flow.

CONTEXT — how the workflow works today:

There are two submission paths that both do the same thing:
  - Path A (original): "Slack Trigger" -> OCR -> "Deterministic Policy Checks"
    -> "AI Contextual Audit" -> "Final Risk Assessment" -> "High Risk?" ->
    "Medium Risk?" -> Slack replies. Node names have NO suffix.
  - Path B (newer): a Slack slash-command opens a modal, then runs the same
    chain. Node names all end in "2" (e.g. "Final Risk Assessment2").

Both paths end with a node called "Final Risk Assessment" / "Final Risk
Assessment2" that outputs an object at $json.final_audit_result containing:
  risk_level          -> one of 'HIGH', 'MEDIUM', 'LOW'
  contextual_summary  -> a plain-English sentence explaining the decision
  category            -> e.g. 'CLIENT_ENTERTAINMENT', 'SUBSISTENCE'

Receipt fields live at:
  $('Audit Engine Input2').item.json.audit_engine_input.receipt
which has: merchant, transaction_date, currency, total, tax, line_items (array),
receipt_id (this is the SLACK FILE ID, not a database id).
And .audit_engine_input.submitted_by is the Slack user id.

Today, ONLY Path B's high-risk branch writes anything: "High Risk?2" (true
output) -> "Prepare High-Risk Sheet Row" (a Code node) -> "Append High-Risk
Expense" (a Google Sheets append to the "Receipts" tab).

THE TARGET — a Google Sheet with ID
1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE and three tabs.

Tab "Receipts", columns in this exact order:
  receipt_id, receipt_date, merchant, line_items, total_amount, tax, category,
  currency, submitter, raw_file_reference, status, created_at, updated_at

Tab "Verdicts", columns in this exact order:
  verdict_id, receipt_id, verdict, reason, created_at

Tab "Decisions" is written by a separate dashboard app — do not touch it.

THE FIVE CHANGES:

1. PERSIST EVERY RECEIPT, NOT JUST HIGH-RISK ONES.
   Move the persistence so it runs for all three risk levels. The cleanest way
   is to put it immediately AFTER "Final Risk Assessment2" and BEFORE "High
   Risk?2", so it runs once for every receipt regardless of which branch fires
   afterwards. Keep the existing Slack routing behaviour unchanged.

2. DO THE SAME ON THE OTHER PATH.
   Path A (the original Slack file-upload path, unsuffixed node names) currently
   persists nothing. Add the same persistence chain after "Final Risk
   Assessment" and before "High Risk?". It must read from the unsuffixed nodes
   ("Audit Engine Input", not "Audit Engine Input2"). This is the path we demo,
   so it matters most.

3. GENERATE A STABLE receipt_id.
   The Code node currently sets receipt_id to the string '=ROW()-1'. Google
   Sheets evaluates that as a live formula, so the ids renumber themselves
   whenever a row is inserted, deleted or sorted — which silently corrupts the
   link between a receipt and its verdict. Replace it:
   - Add a Google Sheets "Get Row(s)" node reading the "Receipts" tab, placed
     before the Code node.
   - In the Code node, compute: the highest numeric receipt_id in those rows,
     plus 1. If the sheet has no data rows, use 1. Ignore any row whose
     receipt_id is not a number.
   - Use that computed number as receipt_id. It must be a plain number, never a
     formula string.

4. FIX TWO FIELD VALUES in the Code node ("Prepare High-Risk Sheet Row"):
   - status: it is currently hardcoded to 'pending'. It must now depend on the
     risk level, because a low-risk expense is approved automatically:
         risk_level LOW              -> 'approved'
         risk_level HIGH or MEDIUM   -> 'pending_review'
     (exact strings - downstream filters match on them).
   - raw_file_reference: set it to the Slack file id (receipt.receipt_id).
     receipt_id must be the number computed in change 3, NOT the Slack file id.

5. ADD A VERDICTS ROW — this is the most important change.
   Right after the Receipts append succeeds, add a second Google Sheets append
   node writing to the "Verdicts" tab, with:
     verdict_id  = any unique number (same max+1 approach as receipt_id is fine)
     receipt_id  = the SAME number just written to Receipts (they must match —
                   this is the join between the two tabs)
     verdict     = map final_audit_result.risk_level:
                     HIGH   -> 'high_risk'
                     MEDIUM -> 'high_risk'
                     LOW    -> 'low'
                   (lowercase; there are only these two verdict values)
     reason      = final_audit_result.contextual_summary
     created_at  = current timestamp in ISO 8601
   Without this row the receipt never appears in the CFO's review dashboard,
   because that dashboard reads verdicts from this tab.

   IMPORTANT - there are only TWO verdicts, and MEDIUM maps to 'high_risk':
   'low' means the AI approved the expense outright and no human will ever look
   at it. 'high_risk' means it goes to the CFO's review queue. MEDIUM is the tier
   where the AI wanted an explanation from the employee, so mapping it to 'low'
   would auto-approve exactly the expenses nobody was confident about. Keep your
   three Slack replies exactly as they are - only the stored verdict collapses to
   two values, not your Slack routing.

Please give me: the updated Code node JavaScript, the configuration for each new
Google Sheets node, and the exact connection changes, for BOTH paths.
```

---

#### How AA (or you) confirms it worked

Submit one receipt through the **Slack file-upload** path, then check the sheet:

1. A new row in **Receipts** with a plain number in `receipt_id` (click the cell — the formula bar must show the number, not `=ROW()-1`).
2. A new row in **Verdicts** whose `receipt_id` is **that same number**.
3. `status` reads `pending_review`.
4. `raw_file_reference` holds the Slack file id (looks like `F0C0FTHGKQV`).
5. Repeat with a low-risk receipt — a row must still appear in both tabs, with `verdict = low` and `status = approved`.
6. Open the dashboard's Review Queue. The high-risk receipt should be sitting there with its summary text; the low-risk one must **not** appear (it was auto-approved) but must show in the Expense Browser.

C3 is done when steps 1-6 pass for all three risk tiers, not just high-risk.

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
    return ("high_risk", "MEDIUM") if medium else ("low", "LOW")
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
**Software:** `requests`. No API key — the inflation source needs none.

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
| `OVER_GUIDELINE` | Over the re-priced figure, but Section 5.2 calls that figure a guideline, not a ceiling → goes to review rather than auto-approving |
| `POLICY_VIOLATION` | Over the re-priced figure on a hard limit → high risk |
| `NO_LIMIT` | No numeric ceiling for this category; the general approval thresholds govern |

The outcome is folded into the verdict's `reason` text rather than becoming a
third verdict value — verdicts are `low` or `high_risk`.

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
3. `pytest -q` — 100 tests, no credentials or network needed.
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

### One global series, not one per country

Inflation comes from a single world aggregate (World Bank
`FP.CPI.TOTL.ZG`, world), applied to every receipt wherever it was incurred.
That is not an approximation of per-country data — it is the right shape for the
question. What gets re-priced is Meridian's own firm-wide GBP limit, and a
£75-a-head limit is £75 a head whether the dinner was in Berlin or Bristol. No
per-country routing, no API key.

The cost, stated plainly: the global series is **annual and published in
arrears** — the latest full year is 2025, where a national index like the UK's
runs monthly to 2026-07. So the adjustment is year-granular, lags by about a
year, and therefore under-states rather than over-states the re-pricing. A base
period's month is ignored (March and November 2019 re-price identically).

### The CPI sheet n8n reads, and standing in for C2

n8n's agent tool sub-workflow reads inflation from a **CPI** tab rather than
calling the World Bank itself — one less external dependency at audit time, and
it guarantees the agent and this repo agree on the numbers.

`scripts/sync_cpi.py` populates it: one row per year with `series_id`, `year`,
`inflation_rate_pct`, `price_index`, `fetched_at`, `source`. The index is chained
from the rates and anchored at 100, so re-pricing a limit set in year A to year B
is `index(B) / index(A)` — a lookup rather than a calculation the agent could get
wrong. `tests/test_cpi_sheet.py` asserts that division reproduces the engine's own
factor exactly, so Slack and the dashboard cannot disagree about the same receipt.

Before the first run: set `CPI_SPREADSHEET_ID` at the top of `api/sheets.py`
(leave unset for a CPI tab in the main spreadsheet), and share that spreadsheet
with the service account's `client_email` as an **Editor** — link-sharing does not
cover API access.

C2 (AA's scheduled pull) is the n8n-native version of exactly this job: a cron
node writing the same tab on a schedule, replacing the manual script.
Two things make this safe to hand over:

* The full series is written to a **CPI** tab by `scripts/sync_cpi.py`
  (`series_id`, `year`, `inflation_rate_pct`, `price_index`, `fetched_at`,
  `source`), which is both what n8n's agent reads and the exact shape C2 should
  write on a schedule.
* When C2 lands, it replaces that script — a cron node writing the same tab.
  Nothing in `api/audit.py` changes.

### Known gaps, stated rather than hidden

* **Currency is not converted.** The handbook is GBP; the sample data is USD. A
  non-GBP claim is still compared against the GBP limit, and the result carries
  `unconverted_currency: true` plus a sentence in the reason telling the reviewer
  to weigh the exchange rate and local purchasing power themselves. Amara called
  both out explicitly, so this is a real gap — closing it needs an FX rate source
  keyed on the transaction date (Handbook 12.2).
* **The inflation figure is annual and about a year in arrears.** A single global
  series is the deliberate simplification (see above); the price is granularity
  and recency. If month-level, current-to-2026 precision is ever needed, the UK
  ONS series `D7BT` is monthly and current — at the cost of reintroducing a
  per-country choice.
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
showed only the bare verdict string), orders newest-first, takes an optional note
that is recorded in the audit trail, and
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
