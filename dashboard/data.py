import json
import re
from datetime import datetime, timezone

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from api.policy import normalise_verdict

DEFAULT_SPREADSHEET_ID = "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "submitter_id",
                   "raw_file_reference", "status", "verdict", "verdict_reason",
                   "created_at", "updated_at", "decided_at"]
CLUSTER_REVIEW_HEADERS = ["review_id", "pattern", "merchant", "receipt_ids",
                          "reviewed_by", "reviewed_at", "notes"]

DECIDER = "amara.osei"


@st.cache_resource
def client():
    if "gcp_service_account" not in st.secrets:
        st.error(
            "Missing Google Sheets credentials. Copy .streamlit/secrets.toml.example to "
            ".streamlit/secrets.toml and fill in your service account key "
            "(see README.md, section 'One-time credentials setup')."
        )
        st.stop()
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)


def spreadsheet_id() -> str:
    return st.secrets.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)


# Streamlit re-runs the whole script on every widget interaction, and each
# uncached load_expenses() costs ~8 Sheets read requests against a 60/min quota.
CACHE_TTL = 60


@st.cache_resource
def spreadsheet():
    return client().open_by_key(spreadsheet_id())


@st.cache_resource
def ensure_ws(name: str, headers: tuple[str, ...]):
    ss = spreadsheet()
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
    if ws.row_values(1) != list(headers):
        ws.update(values=[list(headers)], range_name="A1")
    return ws


def receipts_ws():
    return ensure_ws("Receipts", tuple(RECEIPT_HEADERS))


def cluster_reviews_ws():
    return ensure_ws("Cluster Reviews", tuple(CLUSTER_REVIEW_HEADERS))


def next_id(ws, id_col: str) -> int:
    records = ws.get_all_records()
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            continue
    return max(ids, default=0) + 1


def parse_line_items(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


# ISO dates (created_at/updated_at/decided_at, and any legacy receipt_date)
# must NOT go through dayfirst=True below — see parse_dates.
_ISO_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse_dates(values: pd.Series) -> pd.Series:
    # receipt_date mixes DD/MM/YYYY (current standard), ISO (audit engine) and
    # MM/DD/YY (SROIE samples). dayfirst=True is needed for the slash formats
    # but corrupts ISO ones (2026-08-01 -> 8 Jan), so ISO rows parse separately.
    values = pd.Series(values)
    is_iso = values.astype("string").str.match(_ISO_LIKE).fillna(False)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if is_iso.any():
        parsed.loc[is_iso] = pd.to_datetime(
            values[is_iso], format="mixed", errors="coerce")
    if (~is_iso).any():
        parsed.loc[~is_iso] = pd.to_datetime(
            values[~is_iso], format="mixed", dayfirst=True, errors="coerce")
    return parsed


def parse_timestamps(values: pd.Series) -> pd.Series:
    # Normalised to tz-naive UTC: created_at/updated_at/decided_at carry an
    # offset, receipt_date does not, and subtracting tz-aware from tz-naive
    # raises TypeError. Filter out strings that don't look like timestamps.
    values = pd.Series(values)
    is_valid = values.astype("string").str.match(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[/-]")
    is_valid = is_valid.fillna(False)

    parsed = pd.to_datetime(values, format="mixed", errors="coerce", utc=True)
    # Coerce invalid timestamps to NaT
    parsed.loc[~is_valid] = pd.NaT

    tz = getattr(parsed.dtype, "tz", None)
    return parsed.dt.tz_localize(None) if tz is not None else parsed


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_receipts() -> pd.DataFrame:
    # `expected_headers` sidesteps gspread's duplicate-header exception if a
    # column gets appended to the live sheet outside this schema (seen live:
    # extra blank/`total spend*` columns from a pivot someone built in the
    # same tab) — extra columns still come back in `records`, and the
    # `columns=RECEIPT_HEADERS` below already drops anything not in scope.
    records = receipts_ws().get_all_records(expected_headers=RECEIPT_HEADERS)
    df = pd.DataFrame(records, columns=RECEIPT_HEADERS)
    if df.empty:
        return df.assign(line_items=pd.Series(dtype="object"),
                         date=pd.Series(dtype="datetime64[ns]"),
                         submitted_at=pd.Series(dtype="datetime64[ns]"),
                         decided_at=pd.Series(dtype="datetime64[ns]"),
                         total=pd.Series(dtype="float64"),
                         receipt_id=pd.Series(dtype="Int64"))
    df["line_items"] = df["line_items"].apply(parse_line_items)
    df["date"] = parse_dates(df["receipt_date"])
    df["submitted_at"] = parse_timestamps(df["created_at"])
    df["decided_at"] = parse_timestamps(df["decided_at"])
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = pd.to_numeric(
        df["receipt_id"], errors="coerce").astype("Int64")
    df["verdict"] = df["verdict"].map(normalise_verdict)
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_cluster_reviews() -> pd.DataFrame:
    return pd.DataFrame(cluster_reviews_ws().get_all_records(),
                        columns=CLUSTER_REVIEW_HEADERS)


def load_expenses() -> pd.DataFrame:
    return load_receipts()


def update_decision(receipt_id: int, decision: str) -> bool:
    ws = receipts_ws()
    id_col = RECEIPT_HEADERS.index("receipt_id") + 1
    cell = ws.find(str(receipt_id), in_column=id_col)
    if not cell:
        return False
    now = datetime.now(timezone.utc).isoformat()
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("status") + 1, decision)
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("decided_at") + 1, now)
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("updated_at") + 1, now)

    load_receipts.clear()
    return True


def record_cluster_review(pattern: str, merchant: str, receipt_ids,
                          reviewed_by: str = DECIDER, notes: str = "") -> int:
    ws = cluster_reviews_ws()
    new_id = next_id(ws, "review_id")
    now = datetime.now(timezone.utc).isoformat()
    ids = ",".join(str(int(r)) for r in sorted(receipt_ids))
    ws.append_row([new_id, pattern, merchant, ids, reviewed_by, now, notes],
                  value_input_option="USER_ENTERED")
    load_cluster_reviews.clear()
    return new_id
