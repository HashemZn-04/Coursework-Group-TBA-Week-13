"""
Google Sheets persistence for the audit engine — the C1 schema as one Receipts
tab.

A receipt is written once, with its risk assignment already known (`verdict`,
`verdict_reason`) and `status` set from it (`approved` for low_risk, otherwise
`pending_review`). `decided_at` is blank until the CFO acts on a `high_risk`
receipt; auto-approved receipts never get one. There is no separate
Verdicts/Decisions tab and no history of re-decisions — only the latest state.

Kept deliberately parallel to `dashboard/data.py`, which reads the same tab.
The two differ only in how they authenticate: this module reads a
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

# ---------------------------------------------------------------------------
# CPI reference sheet — read by n8n's AI agent tool sub-workflow.
#
# https://docs.google.com/spreadsheets/d/1KQm1Zt9FncSInMHl6aPBY-2UfHGoiMvQ043DgRhWfow/edit
#
# This is the only place the id belongs — `scripts/sync_cpi.py` and everything
# else read it from here, so there is one value to change rather than several
# that can silently disagree about which sheet was written.
#
# The sheet must have the service account's client_email (from
# service_account.json) added as an **Editor**. "Anyone with the link" does not
# cover API access; without it every write here fails with a 403.
# ---------------------------------------------------------------------------
CPI_SPREADSHEET_ID = os.environ.get(
    "CPI_SPREADSHEET_ID", "1KQm1Zt9FncSInMHl6aPBY-2UfHGoiMvQ043DgRhWfow")

#: The tab that already exists in that spreadsheet — matched exactly, so the
#: sync writes into it rather than creating a second, near-identical tab.
CPI_TAB = "CPI Benchmark"
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "raw_file_reference",
                   "status", "verdict", "verdict_reason",
                   "created_at", "updated_at", "decided_at"]
#: I2 — Amara marking a detected spending pattern as reviewed.
#:
#: A pattern is derived, not stored: it is recomputed from the Receipts tab
#: every time the page loads, so the review has to be recorded against the
#: claims it covered rather than against a row id. `receipt_ids` is that
#: identity — the exact set she looked at. If the group later gains a claim the
#: set no longer matches and the pattern comes back unreviewed, which is right:
#: she cleared a different set, and a new member is new information.
#:
#: This is its own tab rather than a Decisions row because a decision is about
#: one receipt and carries an approve/reject that pays or withholds money. A
#: pattern review is about a group and pays nothing; folding it into Decisions
#: would put rows in the money trail that are not decisions about money.
CLUSTER_REVIEW_HEADERS = ["review_id", "pattern", "merchant", "receipt_ids",
                          "reviewed_by", "reviewed_at", "notes"]
#: The CPI reference table. One row per year of the World Bank's global
#: inflation series, refreshed by `scripts/sync_cpi.py`.
#:
#: `price_index` is the chained level chained from the annual rates and anchored
#: at 100 in the first year, which is what makes this table directly usable
#: without re-deriving anything: to re-price a limit set in year A to year B,
#: read both rows and multiply by index(B) / index(A). That is the one operation
#: n8n's agent needs, and it is a lookup rather than a calculation.
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


def _ensure_ws(name, headers, spreadsheet_id=None):
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
    return _ensure_ws("Receipts", RECEIPT_HEADERS)


def cluster_reviews_ws():
    return _ensure_ws("Cluster Reviews", CLUSTER_REVIEW_HEADERS)


def cpi_ws():
    """The CPI tab, in its own spreadsheet if CPI_SPREADSHEET_ID is set."""
    return _ensure_ws(CPI_TAB, CPI_HEADERS, CPI_SPREADSHEET_ID)


def _next_id(ws, id_col):
    records = ws.get_all_records()
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            # tolerate malformed IDs from other writers (e.g. n8n's "=ROW()-1")
            continue
    return max(ids, default=0) + 1


def insert_receipt(fields: dict) -> int:
    """Write one receipt, verdict and status already decided by the caller.

    `decided_at` is always blank at creation — it is stamped only when the CFO
    later acts on a `high_risk` receipt (see `update_receipt_decision`).
    """
    ws = receipts_ws()
    new_id = _next_id(ws, "receipt_id")
    now = datetime.now(timezone.utc).isoformat()
    row = {**{h: "" for h in RECEIPT_HEADERS}, **fields, "receipt_id": new_id,
           "status": fields.get("status", "pending_review"), "created_at": now, "updated_at": now,
           "decided_at": "",
           "line_items": json.dumps(fields.get("line_items", []))}
    ws.append_row([row[h] for h in RECEIPT_HEADERS],
                  value_input_option="USER_ENTERED")
    return new_id


def update_receipt_decision(receipt_id: int, status: str,
                            decided_at: str | None = None) -> bool:
    """Record the CFO's approve/reject action directly on the Receipts row.

    The verdict column is left untouched — it is the engine's risk read, not
    the human outcome — and only `status`/`decided_at` change. Returns False if
    no row matches `receipt_id`.
    """
    ws = receipts_ws()
    for i, record in enumerate(ws.get_all_records()):
        if _matches(record, "receipt_id", receipt_id):
            row = i + 2  # header row, then 1-indexed
            ws.update_cell(row, RECEIPT_HEADERS.index("status") + 1, status)
            ws.update_cell(row, RECEIPT_HEADERS.index("decided_at") + 1,
                           decided_at or datetime.now(timezone.utc).isoformat())
            ws.update_cell(row, RECEIPT_HEADERS.index("updated_at") + 1,
                           datetime.now(timezone.utc).isoformat())
            return True
    return False


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


def audit_trail(receipt_id: int) -> dict | None:
    """Everything recorded about one receipt — submission, verdict and decision
    all live on the same row now, so this is just that row."""
    return get_receipt(receipt_id)


def write_cpi_series(rates: dict[int, float], series_id: str,
                     source: str = "worldbank") -> int:
    """Replace the CPI tab with the full series, one row per year.

    A full replace rather than an append: this table mirrors an upstream series
    that gets revised, so appending would leave two rows for the same year and
    the reader would have no way to tell which is current.

    Returns the number of year rows written.
    """
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
