import json
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")

# https://docs.google.com/spreadsheets/d/1KQm1Zt9FncSInMHl6aPBY-2UfHGoiMvQ043DgRhWfow/edit
CPI_SPREADSHEET_ID = os.environ.get(
    "CPI_SPREADSHEET_ID", "1KQm1Zt9FncSInMHl6aPBY-2UfHGoiMvQ043DgRhWfow")

CPI_TAB = "CPI Benchmark"
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "submitter_id",
                   "raw_file_reference", "status", "verdict", "verdict_reason",
                   "created_at", "updated_at", "decided_at"]
CLUSTER_REVIEW_HEADERS = ["review_id", "pattern", "merchant", "receipt_ids",
                          "reviewed_by", "reviewed_at", "notes"]
CPI_HEADERS = ["series_id", "year", "inflation_rate_pct", "price_index",
               "fetched_at", "source"]

_client = None


def client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def ensure_ws(name, headers, spreadsheet_id=None):
    ss = client().open_by_key(spreadsheet_id or SPREADSHEET_ID)
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
    if ws.row_values(1) != headers:
        # gspread 6.x: values first, range_name second
        ws.update(values=[headers], range_name="A1")
    return ws


def receipts_ws():
    return ensure_ws("Receipts", RECEIPT_HEADERS)


def cluster_reviews_ws():
    return ensure_ws("Cluster Reviews", CLUSTER_REVIEW_HEADERS)


def cpi_ws():
    return ensure_ws(CPI_TAB, CPI_HEADERS, CPI_SPREADSHEET_ID)


def next_id(ws, id_col, expected_headers=None):
    records = ws.get_all_records(expected_headers=expected_headers)
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            continue
    return max(ids, default=0) + 1


def insert_receipt(fields: dict) -> int:
    ws = receipts_ws()
    new_id = next_id(ws, "receipt_id", RECEIPT_HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    row = {**{h: "" for h in RECEIPT_HEADERS}, **fields, "receipt_id": new_id,
           "status": fields.get("status", "pending_review"), "created_at": now, "updated_at": now,
           "decided_at": "",
           "line_items": json.dumps(fields.get("line_items", []))}
    # RAW, not USER_ENTERED: Sheets' smart date detection reads an ambiguous
    # DD/MM/YYYY receipt_date (day <= 12) using its own locale and can
    # silently swap day and month (confirmed live: "05/01/2026" round-tripped
    # as "1/5/26" — 1 May, not 5 January). RAW stores the literal text;
    # numeric columns still come back as numbers regardless.
    ws.append_row([row[h] for h in RECEIPT_HEADERS], value_input_option="RAW")
    return new_id


def update_receipt_decision(receipt_id: int, status: str,
                            decided_at: str | None = None) -> bool:
    ws = receipts_ws()
    for i, record in enumerate(ws.get_all_records(expected_headers=RECEIPT_HEADERS)):
        if matches(record, "receipt_id", receipt_id):
            row = i + 2  # header row, then 1-indexed
            ws.update_cell(row, RECEIPT_HEADERS.index("status") + 1, status)
            ws.update_cell(row, RECEIPT_HEADERS.index("decided_at") + 1,
                           decided_at or datetime.now(timezone.utc).isoformat())
            ws.update_cell(row, RECEIPT_HEADERS.index("updated_at") + 1,
                           datetime.now(timezone.utc).isoformat())
            return True
    return False


def matches(record: dict, id_col: str, receipt_id: int) -> bool:
    try:
        return int(record.get(id_col)) == int(receipt_id)
    except (TypeError, ValueError):
        return False


def get_receipt(receipt_id: int) -> dict | None:
    for record in receipts_ws().get_all_records(expected_headers=RECEIPT_HEADERS):
        if matches(record, "receipt_id", receipt_id):
            return record
    return None


def audit_trail(receipt_id: int) -> dict | None:
    return get_receipt(receipt_id)


def write_cpi_series(rates: dict[int, float], series_id: str,
                     source: str = "worldbank") -> int:
    ws = cpi_ws()
    now = datetime.now(timezone.utc).isoformat()

    level = 100.0
    rows = []
    for year in sorted(rates):
        rows.append([series_id, year, round(rates[year], 6), round(level, 6),
                     now, source])
        level *= 1 + rates[year] / 100

    ws.clear()
    ws.update(values=[CPI_HEADERS] + rows, range_name="A1",
              value_input_option="USER_ENTERED")
    return len(rows)
