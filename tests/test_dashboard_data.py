"""The dashboard's read/write layer against the same three tabs.

This is where the sheet's untidiness has to be absorbed: everything comes back
as strings, n8n has written at least one non-numeric receipt_id, and a
hand-edited cell can hold anything. A page that raises is a page Amara cannot
use, so the rule these tests enforce is "degrade, never crash".
"""

import pandas as pd

from dashboard import data


def _seed(tabs, receipts=(), verdicts=(), decisions=()):
    for row in receipts:
        tabs["Receipts"].append_row(row)
    for row in verdicts:
        tabs["Verdicts"].append_row(row)
    for row in decisions:
        tabs["Decisions"].append_row(row)


RECEIPT_1 = [1, "2026-08-14", "The Ivy", '[{"description": "Dinner", "amount": 264, "quantity": 3}]',
             264.00, 24.00, "client_entertainment", "GBP", "U04ALEX", "b.jpg",
             "pending_review", "", ""]
RECEIPT_2 = [2, "2026-08-01", "Pret", "[]", 9.20, 0, "subsistence", "GBP",
             "U04SAM", "a.jpg", "approved", "", ""]


def test_load_expenses_merges_the_latest_verdict_onto_each_receipt(sheet_tabs):
    _seed(sheet_tabs, receipts=[RECEIPT_1, RECEIPT_2], verdicts=[
        [1, 1, "flagged", "First pass", "2026-08-14T09:00:00+00:00"],
        [2, 1, "high_risk", "Revised after explanation", "2026-08-15T09:00:00+00:00"],
        [3, 2, "compliant", "Within limits", "2026-08-01T09:00:00+00:00"],
    ])
    df = data.load_expenses().set_index("receipt_id")

    # Two verdicts exist for receipt 1; the newest wins.
    assert df.loc[1, "verdict"] == "high_risk"
    assert df.loc[1, "reason"] == "Revised after explanation"
    assert df.loc[2, "verdict"] == "compliant"
    assert df.loc[1, "total"] == 264.0
    assert df.loc[1, "line_items"][0]["description"] == "Dinner"


def test_receipt_without_a_verdict_still_appears(sheet_tabs):
    """The C3 gap in the live pipeline means receipts land with no Verdicts row.
    They must still show up in the browser and the spend totals, not vanish."""
    _seed(sheet_tabs, receipts=[RECEIPT_1, RECEIPT_2],
          verdicts=[[1, 2, "compliant", "Within limits", "2026-08-01T09:00:00+00:00"]])
    df = data.load_expenses()
    assert len(df) == 2
    assert pd.isna(df.set_index("receipt_id").loc[1, "verdict"])


def test_n8n_row_ids_that_are_not_numbers_do_not_break_the_merge(sheet_tabs):
    """n8n writes the literal '=ROW()-1' into receipt_id on one path. Those rows
    cannot be joined to a verdict, but they must not take the join down."""
    _seed(sheet_tabs,
          receipts=[RECEIPT_1, ["=ROW()-1", "2026-08-02", "Uber", "[]", 18.0, 0,
                                "travel", "GBP", "U04SAM", "c.jpg", "pending", "", ""]],
          verdicts=[[1, 1, "flagged", "Over the per-head guideline", "2026-08-14T09:00:00+00:00"],
                    ["=ROW()-1", "=ROW()-1", "high_risk", "Orphaned", "2026-08-02T09:00:00+00:00"]])
    df = data.load_expenses()

    assert len(df) == 2
    assert df["verdict"].iloc[0] == "flagged"
    assert pd.isna(df["verdict"].iloc[1])


def test_malformed_line_items_degrade_to_an_empty_list(sheet_tabs):
    _seed(sheet_tabs, receipts=[
        [1, "2026-08-14", "A", "not json at all", 10, 0, "travel", "GBP", "U", "r", "approved", "", ""],
        [2, "2026-08-14", "B", '{"not": "a list"}', 10, 0, "travel", "GBP", "U", "r", "approved", "", ""],
        [3, "2026-08-14", "C", "", 10, 0, "travel", "GBP", "U", "r", "approved", "", ""],
    ])
    assert data.load_receipts()["line_items"].tolist() == [[], [], []]


def test_unreadable_dates_and_totals_become_na_not_exceptions(sheet_tabs):
    _seed(sheet_tabs, receipts=[
        [1, "not a date", "A", "[]", "not a number", 0, "travel", "GBP", "U", "r",
         "approved", "", ""]])
    row = data.load_receipts().iloc[0]
    assert pd.isna(row["date"]) and pd.isna(row["total"])


def test_empty_sheet_returns_an_empty_frame_with_the_verdict_columns(sheet_tabs):
    df = data.load_expenses()
    assert df.empty
    assert {"verdict", "reason"} <= set(df.columns)


# --------------------------------------------------------------------------- #
# D2 — recording a decision (what the Review Queue buttons call)
# --------------------------------------------------------------------------- #

def test_record_decision_appends_a_row_and_updates_the_receipt(sheet_tabs):
    _seed(sheet_tabs, receipts=[RECEIPT_1, RECEIPT_2])

    decision_id = data.record_decision(2, "approved", notes="Confirmed by Sam")

    assert decision_id == 1
    decision = sheet_tabs["Decisions"].get_all_records()[0]
    assert decision["receipt_id"] == "2"
    assert decision["decision"] == "approved"
    assert decision["decided_by"] == data.DECIDER
    assert decision["notes"] == "Confirmed by Sam"
    assert decision["decided_at"]

    # The receipt's own status moves in step, so the Expense Browser and
    # /api/expenses agree with the audit trail.
    receipts = {r["receipt_id"]: r for r in sheet_tabs["Receipts"].get_all_records()}
    assert receipts["2"]["status"] == "approved"
    assert receipts["2"]["updated_at"]
    assert receipts["1"]["status"] == "pending_review"   # untouched


def test_decisions_accumulate_rather_than_overwrite(sheet_tabs):
    """QA's D4 ticket checks that no decision record is ever overwritten."""
    _seed(sheet_tabs, receipts=[RECEIPT_1])
    data.record_decision(1, "rejected", notes="No business purpose given")
    data.record_decision(1, "approved", notes="Explained after the fact")

    decisions = sheet_tabs["Decisions"].get_all_records()
    assert [d["decision"] for d in decisions] == ["rejected", "approved"]
    assert [d["decision_id"] for d in decisions] == ["1", "2"]


def test_decision_on_an_unknown_receipt_is_still_recorded(sheet_tabs):
    """Losing the audit record because the receipt row moved would be worse than
    a decision row pointing at a missing receipt."""
    assert data.record_decision(42, "approved") == 1
    assert sheet_tabs["Decisions"].get_all_records()[0]["receipt_id"] == "42"


def test_next_id_skips_malformed_ids(sheet_tabs):
    _seed(sheet_tabs, decisions=[["=ROW()-1", 1, "approved", "amara.osei", "", ""],
                                 [7, 1, "approved", "amara.osei", "", ""]])
    assert data._next_id(sheet_tabs["Decisions"], "decision_id") == 8
