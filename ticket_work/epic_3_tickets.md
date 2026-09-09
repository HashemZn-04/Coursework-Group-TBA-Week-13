# Epic C — The Intelligent Audit Engine: Ticket Guide

> **Architecture change (2026-09-09): Postgres → Google Sheets.**
> The team dropped Postgres in favor of a Google Sheet as the system of record for receipts, verdicts, and decisions — faster to stand up inside a one-week build, no local DB/RDS to provision, and every teammate can eyeball the data live. The sheet: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE/edit
>
> It already has three tabs — **Receipts**, **Verdicts**, **Decisions** — one per table from the original `database/setup.sql` design. They're currently empty (no header row yet); the setup steps below create the headers on first run. Every code sample in this guide reads/writes those three tabs via `gspread` instead of `psycopg2`/SQL. The `database/` folder (`setup.sql`, `seed.py`, `queries.sql`) is now legacy — left in the repo for reference, not used going forward.

## Big-picture findings (unchanged from the Postgres version of this guide)

1. **C1 is done** — schema now lives as the 3 sheet tabs below instead of 3 Postgres tables. Same fields, same intent.
2. **C3's real blocker (A3 Governance Prompt) doesn't exist as a finished artifact yet.** AA already built a working draft directly inside the n8n workflow — a generic "contextual reasonableness" system prompt plus two hardcoded rules (£2,000 CFO threshold, £250 line-manager threshold, 1-month cutoff). Real, usable v1 — just not the full handbook ruleset. Build on it rather than wait.
3. **C2 (CPI pull) hasn't been built at all** — no cron node, no CPI/FRED/BLS reference anywhere in n8n. Technically blocks C4; workaround below unblocks you today.
4. **AA's n8n workflow calls OpenAI directly** from the "AI Contextual Audit" node — not a DA-owned API. An orphaned "Store Expense Record" node pair is wired to nothing, so nothing persists anywhere right now. Closing C3/C4/C5 for real means building the API below and getting AA to repoint that one node at it.

Jira mapping: C1=MCP-21 (done), C3=MCP-25, C4=MCP-27, C5=MCP-31, C6=MCP-34. (C2 is AA's, C7 is Mason's.)

**Recommended order:** C6 → C3 → C4 → C5.

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
                        "payment_method", "category", "currency", "submitter", "raw_file_reference",
                        "source_channel", "status", "created_at", "updated_at"]
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

---

## C3 — Policy Match against Governance Prompt (MCP-25)

**Dependencies:** A3 content (workaround: reuse/extend AA's existing n8n system prompt — see finding #2 above). **Can start now: yes.**
**Software:** Flask app, OpenAI SDK, `gspread`.

1. Create `api/governance_prompt.py` with `SYSTEM_PROMPT = """..."""` — start from AA's existing n8n prompt (found in the "AI Contextual Audit" node) and extend it with the concrete rules Amara actually confirmed:
   - CFO approval threshold is **$2,000** (Amara's verbal correction — printed handbook's £1,000 is stale).
   - Line-manager approval: £250–£2,000.
   - Receipts older than 1 month: **auto-reject, no exceptions**.
   - Reasonableness test = "would this help you do your job."
   - Non-listed software needs manager + IT sign-off regardless of cost.
   - Foreign-currency receipts: weigh purchasing power, not just FX rate.
   - Flag (don't auto-reject) split-receipting patterns.
   Sync with PM before calling this final — this content is technically A3.
2. Create `api/audit.py`:
   ```python
   import os, json
   from openai import OpenAI
   from api.governance_prompt import SYSTEM_PROMPT

   client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

   SCHEMA = {  # copy verbatim from the n8n "AI Contextual Audit" node
       "type": "object", "additionalProperties": False,
       "properties": {
           "business_purpose_clear": {"type": "boolean"},
           "business_relevance": {"type": "string", "enum": ["CLEAR","PLAUSIBLE","UNCLEAR","LIKELY_PERSONAL"]},
           "reasonableness": {"type": "string", "enum": ["REASONABLE","QUESTIONABLE","UNREASONABLE","INSUFFICIENT_INFORMATION"]},
           "category": {"type": "string", "enum": ["TRAVEL","ACCOMMODATION","SUBSISTENCE","CLIENT_ENTERTAINMENT",
               "STAFF_ENTERTAINMENT","SOFTWARE_TECHNOLOGY","TRAINING","OFFICE_SUPPLIES","POSTAGE_COURIER",
               "PROFESSIONAL_SUBSCRIPTION","MISCELLANEOUS","OTHER"]},
           "risk_factors": {"type": "array", "items": {"type": "string"}},
           "positive_factors": {"type": "array", "items": {"type": "string"}},
           "recommended_action": {"type": "string", "enum": ["PASS","NEEDS_EMPLOYEE_EXPLANATION","NEEDS_HUMAN_REVIEW"]},
           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
           "summary": {"type": "string"},
       },
       "required": ["business_purpose_clear","business_relevance","reasonableness","category",
                    "risk_factors","positive_factors","recommended_action","confidence","summary"],
   }

   def run_contextual_audit(audit_reasoning_input: dict) -> dict:
       resp = client.responses.create(
           model="gpt-5",
           input=[
               {"role": "system", "content": SYSTEM_PROMPT},
               {"role": "user", "content": f"Assess this expense:\n\n{json.dumps(audit_reasoning_input, indent=2)}"},
           ],
           text={"format": {"type": "json_schema", "name": "expense_contextual_audit", "strict": True, "schema": SCHEMA}},
       )
       return json.loads(resp.output_text)

   def final_verdict(policy_checks: dict, audit: dict) -> tuple[str, str]:
       """Mirrors n8n's 'Final Risk Assessment' node — keep in sync if that logic changes."""
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
3. Add the route to `api/app.py`:
   ```python
   from api.audit import run_contextual_audit, final_verdict
   from api.sheets import insert_receipt, insert_verdict

   @app.post("/api/audit")
   def audit_receipt():
       payload = request.get_json()
       policy_checks = {"human_review_required": payload.get("human_review_required", False),
                         "approvals_required": payload.get("approvals_required", [])}
       audit = run_contextual_audit(payload)
       verdict, risk_level = final_verdict(policy_checks, audit)

       receipt_id = insert_receipt({
           "receipt_date": payload.get("transaction_date"), "merchant": payload.get("merchant"),
           "line_items": payload.get("line_items", []), "total_amount": payload.get("total"),
           "tax": payload.get("tax"), "category": audit["category"].lower(),
           "currency": payload.get("currency"), "submitter": payload.get("submitted_by"),
           "source_channel": "slack", "status": "pending_review",
       })
       insert_verdict(receipt_id, verdict, audit["summary"])

       return {**audit, "risk_level": risk_level, "verdict": verdict, "receipt_id": receipt_id}
   ```
4. Restart Flask, test with curl:
   ```
   curl -X POST http://localhost:5000/api/audit -H "Content-Type: application/json" -d '{
     "expense_id":"test-1","submitted_by":"j.chen","merchant":"Delta Airlines","transaction_date":"2026-08-01",
     "currency":"USD","total":450,"line_items":[{"description":"flight","amount":450,"quantity":1}],
     "deterministic_flags":[],"approvals_required":[],"human_review_required":false}'
   ```
   Confirm a JSON verdict comes back, and open the Google Sheet in your browser — a new row should appear in **Receipts** and one in **Verdicts** within a second or two (Sheets updates live).
5. Coordinate the n8n rewire with AA (same as before): open n8n → **"AI Contextual Audit"** node → change URL from `https://api.openai.com/v1/responses` to your Flask endpoint (use `ngrok http 5000` if AA's n8n can't reach your machine directly) → simplify the request body to just `{{ $json.audit_reasoning_input }}` → remove the OpenAI credential → then open **"Parse Audit Result"** and simplify it to read `$json.body` directly instead of walking OpenAI's response envelope.
6. Done once a live-submitted receipt produces a stored verdict + reasoning in the sheet within a few seconds.

---

## C4 — Contextual Validation, inflation-aware (MCP-27)

**Dependencies:** C2's benchmark data (not built) — workaround below unblocks you today. Attaches to C3's endpoint.
**Software:** Same Flask app, free FRED API key, `requests`.

1. Get a FRED key: `fred.stlouisfed.org` → **My Account** → **Register**/sign in → **My Account → API Keys** → **Request API Key** → copy it.
2. Add to `.gitignore`-respecting local env (e.g. export it in your shell, or add a small `.env` + `python-dotenv` just for this key — your call) as `FRED_API_KEY`.
3. Add to `api/audit.py`:
   ```python
   import os, requests
   from functools import lru_cache

   @lru_cache(maxsize=1)
   def latest_cpi():
       r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
           "series_id": "CPIAUCSL", "api_key": os.environ["FRED_API_KEY"],
           "file_type": "json", "sort_order": "desc", "limit": 1,
       })
       return float(r.json()["observations"][0]["value"])

   def inflation_adjusted_limit(static_limit: float, base_index: float = 255.0) -> float:
       return round(static_limit * (latest_cpi() / base_index), 2)

   def good_deal_or_violation(total: float, static_limit: float) -> str:
       adjusted = inflation_adjusted_limit(static_limit)
       if total > static_limit and total <= adjusted:
           return "GOOD_DEAL"
       if total <= static_limit and total > adjusted:
           return "POLICY_VIOLATION"
       return "COMPLIANT" if total <= adjusted else "POLICY_VIOLATION"
   ```
   (No `benchmarks` sheet tab needed for the demo — `lru_cache` means one live FRED call per process run, standing in for C2's scheduled pull. When AA finishes C2, swap this for reading a `Benchmarks` tab instead.)
4. Wire it into `/api/audit`: call `good_deal_or_violation(payload["total"], static_limit_for(audit["category"]))`, fold the result into the `reason` text written to the **Verdicts** tab — treat "Good Deal"/"Policy Violation" as reasoning detail, not a 4th verdict value (verdicts are always `compliant`/`flagged`/`high_risk`).
5. Test the required constructed example: a receipt priced above the static 2019 limit but within the inflation-adjusted one should classify as `COMPLIANT`/`GOOD_DEAL`, not flagged. Log this example (curl request/response) — that satisfies the AC.

---

## C5 — High-Risk routing & natural-language summary (MCP-31)

**Dependencies:** C3 + C4 (done above). **Software:** Same Flask app, n8n web UI, Slack.

1. Confirm `/api/audit`'s response already includes `summary` — nothing new to add, C3 covers this.
2. In n8n, check **"High-Risk Expense Slack Routing"**, **"Request Employee Explanation"**, **"Low Risk Compliance Feedback"** nodes reference wherever your summary field now lives (update the expression if you simplified "Parse Audit Result" in C3 step 5).
3. Submit a real test receipt through Slack, confirm the reply includes merchant/amount/reason matching what's now in the **Verdicts** tab.
4. Confirm the dashboard side: your C6 endpoint is the "available via API" half of this ticket — no new dashboard code required for C5 itself.
5. Done once a high-risk test receipt produces a Slack message *and* a row in **Verdicts** you can pull back out via `/api/expenses`.
