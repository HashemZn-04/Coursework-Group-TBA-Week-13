"""
Google Sheets persistence for the audit engine — the C1 schema as three tabs.

Kept deliberately parallel to `dashboard/data.py`, which reads the same three
tabs. The two differ only in how they authenticate: this module reads a
`service_account.json` file (server-side, for the Flask API), the dashboard
reads `st.secrets` (Streamlit Cloud has no filesystem to put a key on). The
header constants are duplicated rather than shared for that reason;
`tests/test_schema_parity.py` fails if the two ever drift apart.
"""

import json
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "raw_file_reference",
                   "status", "created_at", "updated_at"]
VERDICT_HEADERS = ["verdict_id", "receipt_id",
                   "verdict", "reason", "created_at"]
DECISION_HEADERS = ["decision_id", "receipt_id",
                    "decision", "decided_by", "decided_at", "notes"]
#: C2's landing table. AA's scheduled CPI pull has not been built yet, so for now
#: this is written by the audit engine itself — one row per CPI observation it
#: actually used — which makes any past verdict re-checkable against the index
#: level it was decided on. When C2 lands it writes the same shape here.
BENCHMARK_HEADERS = ["series_id", "period", "value", "fetched_at", "source"]

_client = None


def client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _ensure_ws(name, headers):
    ss = client().open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
    if ws.row_values(1) != headers:
        # gspread 6.x: values first, range_name second
        ws.update(values=[headers], range_name="A1")
    return ws


def receipts_ws(): return _ensure_ws("Receipts", RECEIPT_HEADERS)
def verdicts_ws(): return _ensure_ws("Verdicts", VERDICT_HEADERS)
def decisions_ws(): return _ensure_ws("Decisions", DECISION_HEADERS)
def benchmarks_ws(): return _ensure_ws("Benchmarks", BENCHMARK_HEADERS)


def _next_id(ws, id_col):
    records = ws.get_all_records()
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            continue  # tolerate malformed IDs from other writers (e.g. n8n's "=ROW()-1")
    return max(ids, default=0) + 1


def insert_receipt(fields: dict) -> int:
    ws = receipts_ws()
    new_id = _next_id(ws, "receipt_id")
    now = datetime.now(timezone.utc).isoformat()
    row = {**{h: "" for h in RECEIPT_HEADERS}, **fields, "receipt_id": new_id,
           "status": fields.get("status", "pending_review"), "created_at": now, "updated_at": now,
           "line_items": json.dumps(fields.get("line_items", []))}
    ws.append_row([row[h] for h in RECEIPT_HEADERS],
                  value_input_option="USER_ENTERED")
    return new_id


def insert_verdict(receipt_id: int, verdict: str, reason: str) -> int:
    ws = verdicts_ws()
    new_id = _next_id(ws, "verdict_id")
    ws.append_row([new_id, receipt_id, verdict, reason, datetime.now(timezone.utc).isoformat()],
                  value_input_option="USER_ENTERED")
    return new_id


def _matches(record: dict, id_col: str, receipt_id: int) -> bool:
    """Row-id comparison that survives the sheet storing IDs as text."""
    try:
        return int(record.get(id_col)) == int(receipt_id)
    except (TypeError, ValueError):
        return False


def get_receipt(receipt_id: int) -> dict | None:
    for record in receipts_ws().get_all_records():
        if _matches(record, "receipt_id", receipt_id):
            return record
    return None


def verdicts_for(receipt_id: int) -> list[dict]:
    return [r for r in verdicts_ws().get_all_records()
            if _matches(r, "receipt_id", receipt_id)]


def decisions_for(receipt_id: int) -> list[dict]:
    return [r for r in decisions_ws().get_all_records()
            if _matches(r, "receipt_id", receipt_id)]


def audit_trail(receipt_id: int) -> dict | None:
    """Everything recorded about one receipt: what was submitted, what the AI
    decided and why, and what the human did about it — C1's acceptance criterion
    in one call, and what QA's D4 ticket walks to verify the trail is intact."""
    receipt = get_receipt(receipt_id)
    if receipt is None:
        return None
    return {
        "receipt": receipt,
        "verdicts": sorted(verdicts_for(receipt_id),
                           key=lambda r: str(r.get("created_at") or "")),
        "decisions": sorted(decisions_for(receipt_id),
                            key=lambda r: str(r.get("decided_at") or "")),
    }


def record_cpi_snapshot(cpi: dict) -> None:
    """Append the CPI observations a verdict was decided on, if not already there.

    Best-effort by design: a benchmark row is provenance, not the verdict, so a
    Sheets hiccup here must never fail an audit that otherwise succeeded.
    """
    try:
        ws = benchmarks_ws()
        existing = {(str(r.get("series_id")), str(r.get("period")))
                    for r in ws.get_all_records()}
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for period_key, value_key in (("base_period", "base_value"),
                                      ("latest_period", "latest_value")):
            key = (str(cpi["series_id"]), str(cpi[period_key]))
            if key in existing:
                continue
            existing.add(key)  # base and latest can be the same month
            rows.append([cpi["series_id"], cpi[period_key], cpi[value_key], now,
                         cpi.get("source", "fred")])
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
    except Exception:  # pylint: disable=broad-except
        pass
