"""
Data access layer for the dashboard, backed by the shared Google Sheet
(https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE)
instead of Postgres. The sheet has three tabs — Receipts, Verdicts, Decisions —
mirroring the original database/setup.sql design field-for-field.

Requires .streamlit/secrets.toml with a [gcp_service_account] block and a
spreadsheet_id (see .streamlit/secrets.toml.example for the template, and
ticket_work/epic_3_tickets.md for the one-time Google Cloud setup steps).
"""
import json
from datetime import datetime, timezone

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

DEFAULT_SPREADSHEET_ID = "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                    "category", "currency", "submitter", "raw_file_reference",
                    "status", "created_at", "updated_at"]
VERDICT_HEADERS = ["verdict_id", "receipt_id", "verdict", "reason", "created_at"]
DECISION_HEADERS = ["decision_id", "receipt_id", "decision", "decided_by", "decided_at", "notes"]

DECIDER = "amara.osei"  # sole approver per discovery notes — no delegation in v1


@st.cache_resource
def _client():
    if "gcp_service_account" not in st.secrets:
        st.error(
            "Missing Google Sheets credentials. Copy .streamlit/secrets.toml.example to "
            ".streamlit/secrets.toml and fill in your service account key "
            "(see ticket_work/epic_3_tickets.md, section 'One-time setup')."
        )
        st.stop()
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)


def _spreadsheet_id() -> str:
    return st.secrets.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)


def _ensure_ws(name: str, headers: list[str]):
    ss = _client().open_by_key(_spreadsheet_id())
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
    if ws.row_values(1) != headers:
        ws.update(values=[headers], range_name="A1")
    return ws


def receipts_ws():
    return _ensure_ws("Receipts", RECEIPT_HEADERS)


def verdicts_ws():
    return _ensure_ws("Verdicts", VERDICT_HEADERS)


def decisions_ws():
    return _ensure_ws("Decisions", DECISION_HEADERS)


def _next_id(ws, id_col: str) -> int:
    records = ws.get_all_records()
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            continue  # tolerate malformed IDs from other writers (e.g. n8n's "=ROW()-1")
    return max(ids, default=0) + 1


def _parse_line_items(value):
    """Line items arrive as a JSON string, but the sheet is hand-editable and
    n8n has written malformed values before now — a bad cell must not take the
    whole dashboard down."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def load_receipts() -> pd.DataFrame:
    records = receipts_ws().get_all_records()
    df = pd.DataFrame(records, columns=RECEIPT_HEADERS)
    if df.empty:
        return df
    df["line_items"] = df["line_items"].apply(_parse_line_items)
    df["date"] = pd.to_datetime(df["receipt_date"], errors="coerce")
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = pd.to_numeric(df["receipt_id"], errors="coerce").astype("Int64")
    return df


def load_verdicts() -> pd.DataFrame:
    return pd.DataFrame(verdicts_ws().get_all_records(), columns=VERDICT_HEADERS)


def load_decisions() -> pd.DataFrame:
    return pd.DataFrame(decisions_ws().get_all_records(), columns=DECISION_HEADERS)


def load_expenses() -> pd.DataFrame:
    """One row per receipt, merged with its latest verdict. Replaces the old
    mock-data load_mock_receipts() — same shape (receipt_id, date, merchant,
    category, total, submitter, verdict, status, ...) but sourced from the
    live sheet instead of data/annotations.xml."""
    receipts = load_receipts()
    if receipts.empty:
        return receipts.assign(verdict=pd.Series(dtype="object"), reason=pd.Series(dtype="object"))

    verdicts = load_verdicts()
    if verdicts.empty:
        receipts["verdict"] = None
        receipts["reason"] = None
        return receipts

    # Match load_receipts()'s Int64 so the merge keys line up; unparseable IDs
    # (n8n has written literal "=ROW()-1" into this column) become NA and simply
    # fail to match rather than raising.
    verdicts["receipt_id"] = pd.to_numeric(
        verdicts["receipt_id"], errors="coerce").astype("Int64")
    latest = (verdicts.dropna(subset=["receipt_id"])
              .sort_values("created_at")
              .groupby("receipt_id", as_index=False).tail(1))
    return receipts.merge(latest[["receipt_id", "verdict", "reason"]],
                          on="receipt_id", how="left")


def record_decision(receipt_id: int, decision: str, decided_by: str = DECIDER, notes: str = "") -> int:
    """Appends to Decisions and updates the receipt's status in place. decision
    is one of 'approved' | 'rejected' | 'escalated'."""
    ws = decisions_ws()
    new_id = _next_id(ws, "decision_id")
    now = datetime.now(timezone.utc).isoformat()
    ws.append_row([new_id, receipt_id, decision, decided_by, now, notes], value_input_option="USER_ENTERED")

    r_ws = receipts_ws()
    id_col = RECEIPT_HEADERS.index("receipt_id") + 1
    cell = r_ws.find(str(receipt_id), in_column=id_col)
    if cell:
        r_ws.update_cell(cell.row, RECEIPT_HEADERS.index("status") + 1, decision)
        r_ws.update_cell(cell.row, RECEIPT_HEADERS.index("updated_at") + 1, now)
    return new_id
