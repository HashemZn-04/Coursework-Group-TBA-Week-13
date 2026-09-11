"""The dashboard's read/write layer against the single Receipts tab.

This is where the sheet's untidiness has to be absorbed: everything comes back
as strings, n8n has written at least one non-numeric receipt_id, and a
hand-edited cell can hold anything. A page that raises is a page Amara cannot
use, so the rule these tests enforce is "degrade, never crash".
"""

import pandas as pd

from dashboard import data


def _seed(tabs, receipts=()):
    for row in receipts:
        tabs["Receipts"].append_row(row)


RECEIPT_1 = [1, "2026-08-14", "The Ivy", '[{"description": "Dinner", "amount": 264, "quantity": 3}]',
             264.00, 24.00, "client_entertainment", "GBP", "U04ALEX", "", "b.jpg",
             "pending_review", "high_risk", "Over the per-head guideline",
             "", "", ""]
RECEIPT_2 = [2, "2026-08-01", "Pret", "[]", 9.20, 0, "subsistence", "GBP",
             "U04SAM", "", "a.jpg", "approved", "low_risk", "Within limits",
             "", "", ""]


def test_load_expenses_reads_the_verdict_already_on_the_row(sheet_tabs):
    _seed(sheet_tabs, receipts=[RECEIPT_1, RECEIPT_2])
    df = data.load_expenses().set_index("receipt_id")

    assert df.loc[1, "verdict"] == "high_risk"
    assert df.loc[1, "verdict_reason"] == "Over the per-head guideline"
    assert df.loc[2, "verdict"] == "low_risk"
    assert df.loc[1, "total"] == 264.0
    assert df.loc[1, "line_items"][0]["description"] == "Dinner"


def test_receipt_without_a_verdict_still_appears(sheet_tabs):
    """A gap in the pipeline means a receipt can land with no verdict yet. It
    must still show up in the browser and the spend totals, not vanish."""
    unassessed = [3, "2026-08-02", "Uber", "[]", 18.0, 0, "travel", "GBP",
                  "U04SAM", "", "c.jpg", "pending_review", "", "", "", "", ""]
    _seed(sheet_tabs, receipts=[RECEIPT_1, unassessed])
    df = data.load_expenses()
    assert len(df) == 2
    assert pd.isna(df.set_index("receipt_id").loc[3, "verdict"])


def test_malformed_line_items_degrade_to_an_empty_list(sheet_tabs):
    _seed(sheet_tabs, receipts=[
        [1, "2026-08-14", "A", "not json at all", 10, 0, "travel",
            "GBP", "U", "", "r", "approved", "", "", "", "", ""],
        [2, "2026-08-14", "B", '{"not": "a list"}', 10, 0, "travel",
            "GBP", "U", "", "r", "approved", "", "", "", "", ""],
        [3, "2026-08-14", "C", "", 10, 0, "travel", "GBP",
            "U", "", "r", "approved", "", "", "", "", ""],
    ])
    assert data.load_receipts()["line_items"].tolist() == [[], [], []]


def test_unreadable_dates_and_totals_become_na_not_exceptions(sheet_tabs):
    _seed(sheet_tabs, receipts=[
        [1, "not a date", "A", "[]", "not a number", 0, "travel", "GBP", "U", "", "r",
         "approved", "", "", "", "", ""]])
    row = data.load_receipts().iloc[0]
    assert pd.isna(row["date"]) and pd.isna(row["total"])


def test_empty_sheet_returns_an_empty_frame_with_the_verdict_columns(sheet_tabs):
    df = data.load_expenses()
    assert df.empty
    assert {"verdict"} <= set(df.columns)


# --------------------------------------------------------------------------- #
# The CFO's approve/reject action
# --------------------------------------------------------------------------- #

def test_update_decision_sets_status_and_decided_at(sheet_tabs):
    _seed(sheet_tabs, receipts=[RECEIPT_1, RECEIPT_2])

    assert data.update_decision(2, "approved") is True

    receipts = {r["receipt_id"]
        : r for r in sheet_tabs["Receipts"].get_all_records()}
    assert receipts["2"]["status"] == "approved"
    assert receipts["2"]["decided_at"]
    assert receipts["2"]["updated_at"]
    assert receipts["1"]["status"] == "pending_review"   # untouched


def test_update_decision_leaves_the_verdict_untouched(sheet_tabs):
    """The verdict is the engine's risk read, not the human outcome; only
    status and decided_at change."""
    _seed(sheet_tabs, receipts=[RECEIPT_1])
    data.update_decision(1, "rejected")

    receipt = sheet_tabs["Receipts"].get_all_records()[0]
    assert receipt["verdict"] == "high_risk"
    assert receipt["status"] == "rejected"


def test_update_decision_on_an_unknown_receipt_returns_false(sheet_tabs):
    assert data.update_decision(42, "approved") is False


def test_receipt_dates_in_different_formats_all_parse(sheet_tabs):
    """The live sheet holds at least two date formats: ISO from the audit
    engine, and `08/20/10 13:12:01` from the SROIE sample receipts. Plain
    to_datetime infers one format from the first row and coerces the rest to
    NaT, which silently undated every sample receipt and dropped them out of
    the Expense Browser's date filter — five of six rows vanished from the
    dashboard with no error shown.
    """
    _seed(sheet_tabs, receipts=[
        [1, "2026-08-01", "Delta Airlines", "[]", 450, 0, "travel",
            "USD", "j.chen", "", "a", "approved", "", "", "", "", ""],
        [2, "08/20/10 13:12:01", "WAL*MART", "[]", 5.11, 0, "office_supplies",
            "USD", "j.chen", "", "b", "approved", "", "", "", "", ""],
        [3, "2026-08-14", "The Ivy", "[]", 264, 24, "client_entertainment",
            "GBP", "a.okafor", "", "c", "approved", "", "", "", "", ""],
    ])
    dates = data.load_receipts()["date"]

    assert dates.notna().all(), "every row above has a readable date"
    assert dates.iloc[1] == pd.Timestamp("2010-08-20 13:12:01")


def test_receipt_dates_read_dd_mm_yyyy_not_mm_dd_yyyy(sheet_tabs):
    """The Receipts tab is now standardised on DD/MM/YYYY. `03/09/2026` must
    read as 3 September, not March, and an ISO row alongside it must still
    parse correctly (dayfirst reordering must not leak into ISO dates)."""
    _seed(sheet_tabs, receipts=[
        [1, "03/09/2026", "Delta Airlines", "[]", 450, 0, "travel",
            "USD", "j.chen", "", "a", "approved", "", "", "", "", ""],
        [2, "2026-08-01", "The Ivy", "[]", 264, 24, "client_entertainment",
            "GBP", "a.okafor", "", "c", "approved", "", "", "", "", ""],
    ])
    dates = data.load_receipts()["date"]

    assert dates.iloc[0] == pd.Timestamp("2026-09-03")
    assert dates.iloc[1] == pd.Timestamp("2026-08-01")


def test_a_genuinely_unreadable_date_is_still_na(sheet_tabs):
    """Tolerating mixed formats must not turn into accepting anything."""
    _seed(sheet_tabs, receipts=[
        [1, "2026-08-01", "A", "[]", 10, 0, "travel", "GBP",
            "u", "", "r", "approved", "", "", "", "", ""],
        [2, "not a date", "B", "[]", 10, 0, "travel", "GBP",
            "u", "", "r", "approved", "", "", "", "", ""],
    ])
    dates = data.load_receipts()["date"]
    assert dates.notna().iloc[0] and pd.isna(dates.iloc[1])


# --------------------------------------------------------------------------- #
# Legacy rows from the three-tier model
# --------------------------------------------------------------------------- #

def test_legacy_verdicts_are_normalised_on_read(sheet_tabs):
    """Rows written before the collapse say "compliant"/"flagged", and rows
    written under the old two-tier vocabulary say "low". They are mapped on
    read so the sheet needs no migration — and `flagged` folds *up* to
    high_risk, because it always meant "a human needs to look at this" and
    folding it down would auto-approve it retroactively."""
    legacy_flagged = [1, "2026-08-14", "The Ivy", "[]", 264.00, 24.00,
                      "client_entertainment", "GBP", "U04ALEX", "", "b.jpg",
                      "pending_review", "flagged", "Legacy middle tier", "", "", ""]
    legacy_compliant = [2, "2026-08-01", "Pret", "[]", 9.20, 0, "subsistence",
                        "GBP", "U04SAM", "", "a.jpg", "approved", "compliant",
                        "Legacy clean", "", "", ""]
    legacy_low = [3, "2026-08-01", "Pret", "[]", 9.20, 0, "subsistence",
                  "GBP", "U04SAM", "", "a.jpg", "approved", "low",
                  "Old two-tier vocabulary", "", "", ""]
    _seed(sheet_tabs, receipts=[legacy_flagged, legacy_compliant, legacy_low])
    df = data.load_expenses().set_index("receipt_id")

    assert df.loc[1, "verdict"] == "high_risk"
    assert df.loc[2, "verdict"] == "low_risk"
    assert df.loc[3, "verdict"] == "low_risk"


def test_the_submission_time_is_readable_alongside_the_receipt_date(sheet_tabs):
    """`created_at` carries a UTC offset and `receipt_date` does not, so the two
    come back with different dtypes unless they are put on one clock. The
    one-month cutoff is the gap between them; subtracting a tz-naive value from
    a tz-aware one raises rather than degrading."""
    _seed(sheet_tabs, receipts=[
        [1, "08/20/10 13:12:01", "WAL*MART", "[]", 5.11, 0, "subsistence", "USD",
         "U0B4SSV8YJE", "", "F0C0", "pending_review", "", "",
         "2026-09-09T12:16:44.931Z", "", ""]])
    row = data.load_receipts().iloc[0]

    assert row["submitted_at"] == pd.Timestamp("2026-09-09 12:16:44.931")
    assert (row["submitted_at"] - row["date"]).days > 30


def test_an_empty_sheet_still_hands_back_the_derived_columns(sheet_tabs):
    """Returning the bare header set made every caller's `.empty` check
    load-bearing: forget one and it is a KeyError on `date` or `total` exactly
    when the sheet is empty, which is a fresh deployment."""
    assert {"date", "total", "submitted_at", "line_items", "decided_at"} <= set(
        data.load_receipts().columns)


# --------------------------------------------------------------------------- #
# I2 — marking a detected pattern as reviewed
# --------------------------------------------------------------------------- #

def test_a_cluster_review_records_the_exact_claims_that_were_reviewed(sheet_tabs):
    """The pattern is recomputed on every page load and has no stable id of its
    own, so the review is recorded against the set of receipts it covered."""
    review_id = data.record_cluster_review("SYNDICATED", "WAL*MART", [4, 2, 3],
                                           notes="Team offsite")
    review = sheet_tabs["Cluster Reviews"].get_all_records()[0]

    assert review_id == 1
    assert review["receipt_ids"] == "2,3,4"
    assert review["pattern"] == "SYNDICATED"
    assert review["reviewed_by"] == data.DECIDER
    assert review["reviewed_at"]
