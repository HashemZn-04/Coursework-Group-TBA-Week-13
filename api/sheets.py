import json
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "raw_file_reference",
                   "status", "created_at", "updated_at"]
VERDICT_HEADERS = ["verdict_id", "receipt_id",
                   "verdict", "reason", "created_at"]
DECISION_HEADERS = ["decision_id", "receipt_id",
                    "decision", "decided_by", "decided_at", "notes"]

_client = None


def client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            "service_account.json", scopes=SCOPES)
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
