"""
Data access layer for the dashboard, backed by the shared Google Sheet
(https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE)
instead of Postgres. The sheet has a single Receipts tab: verdict,
verdict_reason and decided_at live on the receipt row itself rather than in
separate Verdicts/Decisions tabs, so there is one row per receipt and only the
latest state — no history of re-decisions.

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

from api.policy import VERDICT_HIGH, VERDICT_LOW, normalise_verdict

DEFAULT_SPREADSHEET_ID = "1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]

RECEIPT_HEADERS = ["receipt_id", "receipt_date", "merchant", "line_items", "total_amount", "tax",
                   "category", "currency", "submitter", "raw_file_reference",
                   "status", "verdict", "verdict_reason",
                   "created_at", "updated_at", "decided_at"]
#: I2 — see `api/sheets.py` for why a pattern review is its own tab and why the
#: set of receipt ids is its identity.
CLUSTER_REVIEW_HEADERS = ["review_id", "pattern", "merchant", "receipt_ids",
                          "reviewed_by", "reviewed_at", "notes"]

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
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)


def _spreadsheet_id() -> str:
    return st.secrets.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)


#: How long a sheet read is reused before going back to the API. Streamlit
#: re-runs the whole script on *every* widget interaction — one slider drag is
#: dozens of re-runs — and each uncached `load_expenses()` costs roughly eight
#: Sheets read requests against a 60-per-minute quota. Without this, moving a
#: filter exhausts the quota in seconds. A minute of staleness is invisible to a
#: reviewer; an API error page is not.
CACHE_TTL = 60


@st.cache_resource
def _spreadsheet():
    """Opening the spreadsheet costs a metadata fetch, so do it once."""
    return _client().open_by_key(_spreadsheet_id())


@st.cache_resource
def _ensure_ws(name: str, headers: tuple[str, ...]):
    """Worksheet handle, creating the tab and its header row if missing.

    Cached per session: the header check is itself a read request, and the
    headers cannot change under us mid-session. `headers` is a tuple because
    cache_resource needs its arguments to be hashable.
    """
    ss = _spreadsheet()
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
    if ws.row_values(1) != list(headers):
        ws.update(values=[list(headers)], range_name="A1")
    return ws


def receipts_ws():
    return _ensure_ws("Receipts", tuple(RECEIPT_HEADERS))


def cluster_reviews_ws():
    return _ensure_ws("Cluster Reviews", tuple(CLUSTER_REVIEW_HEADERS))


def _next_id(ws, id_col: str) -> int:
    records = ws.get_all_records()
    ids = []
    for r in records:
        try:
            ids.append(int(r[id_col]))
        except (ValueError, TypeError):
            # tolerate malformed IDs from other writers (e.g. n8n's "=ROW()-1")
            continue
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


def _parse_dates(values: pd.Series) -> pd.Series:
    """Parse receipt dates that do not share one format.

    The sheet genuinely holds several: ISO `2026-08-01` from the audit engine,
    and `08/20/10 13:12:01` from the SROIE sample receipts. Plain
    `to_datetime(errors="coerce")` infers a format from the first non-null value
    and coerces everything that does not match it to NaT — which silently
    undated every sample receipt and dropped them out of the date filter.
    `format="mixed"` parses each value on its own terms instead.
    """
    return pd.to_datetime(values, format="mixed", errors="coerce")


def _parse_timestamps(values: pd.Series) -> pd.Series:
    """Parse a machine-written timestamp column to **tz-naive** UTC.

    `created_at`, `updated_at` and `decided_at` are written as
    `datetime.now(timezone.utc).isoformat()` here and as `new Date()
    .toISOString()` by n8n — both carry an offset, where `receipt_date` from
    `_parse_dates` does not. Subtracting one from the other raises
    ``TypeError: Cannot subtract tz-naive and tz-aware datetime-like objects``,
    so every comparison between "when was this spent" and "when was it
    submitted" would blow up on live rows. Normalising to UTC and then dropping
    the offset puts both on the same clock: the instants are already absolute,
    and nothing here needs a local wall-clock reading.
    """
    parsed = pd.to_datetime(values, format="mixed", errors="coerce", utc=True)
    tz = getattr(parsed.dtype, "tz", None)
    return parsed.dt.tz_localize(None) if tz is not None else parsed


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_receipts() -> pd.DataFrame:
    records = receipts_ws().get_all_records()
    df = pd.DataFrame(records, columns=RECEIPT_HEADERS)
    if df.empty:
        # Hand back the derived columns even with no rows. Returning the bare
        # header set instead made every caller's `.empty` check load-bearing:
        # forget one and you get a KeyError on `date` or `total` exactly when
        # the sheet is empty, which is a fresh deployment and every test that
        # seeds nothing.
        return df.assign(line_items=pd.Series(dtype="object"),
                         date=pd.Series(dtype="datetime64[ns]"),
                         submitted_at=pd.Series(dtype="datetime64[ns]"),
                         decided_at=pd.Series(dtype="datetime64[ns]"),
                         total=pd.Series(dtype="float64"),
                         receipt_id=pd.Series(dtype="Int64"))
    df["line_items"] = df["line_items"].apply(_parse_line_items)
    df["date"] = _parse_dates(df["receipt_date"])
    # When the row reached the sheet, as opposed to when the money was spent.
    # The one-month cutoff is the gap between the two, so both have to be
    # readable and on the same clock — see `_parse_timestamps`.
    df["submitted_at"] = _parse_timestamps(df["created_at"])
    df["decided_at"] = _parse_timestamps(df["decided_at"])
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = pd.to_numeric(
        df["receipt_id"], errors="coerce").astype("Int64")
    # Rows written before the three-tier model was collapsed still say
    # "compliant"/"flagged", and rows written under the old two-tier vocabulary
    # still say "low". Normalising on read means the queue and the totals are
    # right without a migration, and stays harmless once the sheet is clean.
    df["verdict"] = df["verdict"].map(normalise_verdict)
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_cluster_reviews() -> pd.DataFrame:
    return pd.DataFrame(cluster_reviews_ws().get_all_records(),
                        columns=CLUSTER_REVIEW_HEADERS)


def load_expenses() -> pd.DataFrame:
    """One row per receipt, verdict and decision already on it. Replaces the
    old mock-data load_mock_receipts() — same shape (receipt_id, date,
    merchant, category, total, submitter, verdict, status, ...) but sourced
    from the live sheet instead of data/annotations.xml."""
    return load_receipts()


def update_decision(receipt_id: int, decision: str) -> bool:
    """Record the CFO's approve/reject action directly on the Receipts row.

    `decision` is 'approved' or 'rejected'. Only high-risk receipts reach this —
    low-risk ones are approved by the engine at audit time and never enter the
    queue. There is no separate Decisions tab: `status` becomes the decision and
    `decided_at` is stamped now. The verdict column is left untouched, since it
    is the engine's risk read, not the human outcome.
    """
    ws = receipts_ws()
    id_col = RECEIPT_HEADERS.index("receipt_id") + 1
    cell = ws.find(str(receipt_id), in_column=id_col)
    if not cell:
        return False
    now = datetime.now(timezone.utc).isoformat()
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("status") + 1, decision)
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("decided_at") + 1, now)
    ws.update_cell(cell.row, RECEIPT_HEADERS.index("updated_at") + 1, now)

    # The reads above are cached for CACHE_TTL, so without this the reviewer
    # clicks Approve and the receipt stays in the queue for a minute — which
    # reads as "the button did nothing" and invites a second click.
    load_receipts.clear()
    return True


def record_cluster_review(pattern: str, merchant: str, receipt_ids,
                          reviewed_by: str = DECIDER, notes: str = "") -> int:
    """Mark one detected spending pattern as reviewed (I2).

    Recorded against the set of receipts it covered rather than against a
    generated cluster id, because the cluster is recomputed from scratch on
    every page load and has no stable identity of its own. See
    `api.clusters.pattern_identity`.

    This records that Amara *looked*; it is not an approval. Money still moves
    through the Review Queue, one receipt at a time.
    """
    ws = cluster_reviews_ws()
    new_id = _next_id(ws, "review_id")
    now = datetime.now(timezone.utc).isoformat()
    ids = ",".join(str(int(r)) for r in sorted(receipt_ids))
    ws.append_row([new_id, pattern, merchant, ids, reviewed_by, now, notes],
                  value_input_option="USER_ENTERED")
    load_cluster_reviews.clear()
    return new_id
