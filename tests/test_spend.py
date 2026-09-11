"""E2 — money at risk vs money prevented, and what "velocity" actually means.

Two rules are load-bearing here and every test below exists to hold one of
them up: **aggregate over receipts, one row each** (there is no separate
decisions tab to double-count from), and **never add two currencies** (or a
USD receipt and a GBP one produce a number in no unit at all).
"""

import pandas as pd

from dashboard import data
from dashboard.spend import (MAX_CHART_BARS, UNKNOWN_CURRENCY, choose_freq,
                             default_currency, prevented_running_total,
                             spend_over_time, spend_summary)
from tests.conftest import expenses


# --------------------------------------------------------------------------- #
# The buckets
# --------------------------------------------------------------------------- #

def test_money_at_risk_and_money_prevented_are_different_numbers():
    """The regression test for this ticket. The old tile summed every high-risk
    receipt and called it leakage, so rejecting a claim moved it by nothing."""
    df = expenses({"receipt_id": 1, "total_amount": 300.0, "verdict": "high_risk",
                  "status": "pending_review"},
                  {"receipt_id": 2, "total_amount": 500.0, "verdict": "high_risk",
                  "status": "rejected", "decided_at": "2026-08-20T09:00:00+00:00"})
    summary = spend_summary(df)

    assert summary.totals.loc["GBP", "at_risk"] == 300.0
    assert summary.totals.loc["GBP", "prevented"] == 500.0


def test_the_buckets_partition_the_claimed_total():
    """Every receipt lands in exactly one bucket, so nothing can be
    double-counted into the saving figure and nothing can silently vanish."""
    df = expenses({"receipt_id": 1, "total_amount": 100.0, "verdict": "low_risk",
                  "status": "approved"},
                  {"receipt_id": 2, "total_amount": 200.0, "verdict": "high_risk",
                  "status": "pending_review"},
                  {"receipt_id": 3, "total_amount": 300.0, "verdict": "high_risk",
                  "status": "rejected", "decided_at": "2026-08-20T09:00:00+00:00"},
                  {"receipt_id": 4, "total_amount": 400.0, "verdict": None},
                  {"receipt_id": 5, "total_amount": 500.0, "verdict": "banana"})
    summary = spend_summary(df)
    row = summary.totals.loc["GBP"]

    assert row["claimed"] == 1500.0
    assert (row["approved"] + row["at_risk"] + row["prevented"]
            + row["unprocessed"] + row["unrecognised"]
            + row["ambiguous"]) == row["claimed"]
    assert row["unrecognised"] == 500.0


def test_an_unassessed_receipt_is_in_claimed_and_in_no_outcome_bucket():
    """A missing verdict is a processing failure, not an outcome. Somebody
    claimed that money, so it is inside Claimed; nothing assessed it, so it is
    neither approved, at risk, nor prevented."""
    df = expenses({"total_amount": 400.0, "verdict": None})
    row = spend_summary(df).totals.loc["GBP"]

    assert row["claimed"] == 400.0
    assert row["unprocessed"] == 400.0
    assert row["approved"] == row["at_risk"] == row["prevented"] == 0.0


def test_a_low_risk_verdict_counts_as_approved():
    """A low-risk receipt is approved by the engine at audit time — status is
    `approved` from the moment it lands."""
    df = expenses(
        {"total_amount": 60.0, "verdict": "low_risk", "status": "approved"})
    assert spend_summary(df).totals.loc["GBP", "approved"] == 60.0


def test_receipts_sharing_an_id_are_held_out_of_the_outcome_buckets():
    """A shared id cannot be trusted as an identity. Both receipts stay in
    Claimed — the money was claimed — and neither is assigned an outcome on a
    guess."""
    df = expenses({"receipt_id": 1, "total_amount": 100.0, "verdict": "high_risk",
                  "status": "rejected"},
                  {"receipt_id": 1, "total_amount": 200.0, "verdict": "high_risk",
                  "status": "rejected"})
    summary = spend_summary(df)

    assert summary.totals.loc["GBP", "claimed"] == 300.0
    assert summary.totals.loc["GBP", "ambiguous"] == 300.0
    assert summary.totals.loc["GBP", "prevented"] == 0.0
    assert summary.duplicate_receipt_ids == 2


def test_an_unreadable_total_does_not_poison_the_sum():
    df = expenses({"receipt_id": 1, "total_amount": "not a number",
                   "verdict": "low_risk", "status": "approved"},
                  {"receipt_id": 2, "total_amount": 50.0, "verdict": "low_risk",
                  "status": "approved"})
    assert spend_summary(df).totals.loc["GBP", "claimed"] == 50.0


def test_an_empty_sheet_gives_an_empty_summary_rather_than_an_error():
    summary = spend_summary(pd.DataFrame())
    assert summary.totals.empty
    assert summary.currencies == []


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #

def test_usd_and_gbp_are_never_added_together():
    df = expenses({"receipt_id": 1, "total_amount": 450.0, "currency": "USD",
                   "verdict": "low_risk", "status": "approved"},
                  {"receipt_id": 2, "total_amount": 264.0, "currency": "GBP",
                   "verdict": "low_risk", "status": "approved"})
    totals = spend_summary(df).totals

    assert set(totals.index) == {"USD", "GBP"}
    assert totals.loc["USD", "claimed"] == 450.0
    assert totals.loc["GBP", "claimed"] == 264.0
    assert 714.0 not in set(totals["claimed"])


def test_a_blank_currency_gets_its_own_bucket():
    df = expenses({"total_amount": 5.11, "currency": "", "verdict": "low_risk",
                  "status": "approved"})
    assert spend_summary(df).totals.loc["", "claimed"] == 5.11


def test_currencies_are_ordered_by_receipt_count_not_by_amount():
    """Ordering by amount would rank 450 USD above 264 GBP, which is the
    comparison this module exists to refuse."""
    df = expenses({"receipt_id": 1, "total_amount": 450.0, "currency": "USD",
                   "verdict": "low_risk", "status": "approved"},
                  {"receipt_id": 2, "total_amount": 10.0, "currency": "GBP",
                   "verdict": "low_risk", "status": "approved"},
                  {"receipt_id": 3, "total_amount": 10.0, "currency": "GBP",
                   "verdict": "low_risk", "status": "approved"})
    assert spend_summary(df).currencies == ["GBP", "USD"]


def test_default_currency_prefers_gbp_when_present():
    assert default_currency(["USD", "GBP"]) == "GBP"


def test_default_currency_falls_back_to_the_commonest_currency():
    """No GBP among the options, so the dropdown opens on whichever currency
    `SpendSummary.currencies` already ranked first (by receipt count)."""
    assert default_currency(["USD", "EUR"]) == "USD"


def test_default_currency_of_no_currencies_is_the_unknown_bucket():
    assert default_currency([]) == UNKNOWN_CURRENCY


# --------------------------------------------------------------------------- #
# Velocity
# --------------------------------------------------------------------------- #

def test_spend_over_time_sums_into_buckets_rather_than_one_point_per_receipt():
    """The live failure of the chart this replaces: several receipts sharing a
    timestamp used to stack into a vertical spike in arbitrary order."""
    rows = [{"receipt_id": i, "receipt_date": "08/20/10 13:12:01",
             "total_amount": 5.11} for i in range(1, 8)]
    timeline = spend_over_time(expenses(*rows), "GBP", freq="MS")

    assert len(timeline) == 1
    assert round(float(timeline["spend"].iloc[0]), 2) == 35.77
    assert int(timeline["receipts"].iloc[0]) == 7


def test_empty_periods_are_drawn_as_zero_rather_than_dropped():
    """A month with no claims is a fact about velocity."""
    df = expenses({"receipt_id": 1, "receipt_date": "2026-01-15"},
                  {"receipt_id": 2, "receipt_date": "2026-04-15"})
    timeline = spend_over_time(df, "GBP", freq="MS")

    assert len(timeline) == 4
    assert list(timeline["spend"])[1:3] == [0.0, 0.0]


def test_the_bucket_widens_until_the_chart_is_legible():
    """A wide date span would otherwise produce thousands of daily bars."""
    wide = pd.Series(pd.to_datetime(["2010-08-20", "2026-08-01"]))
    narrow = pd.Series(pd.to_datetime(["2026-08-01", "2026-08-20"]))

    assert choose_freq(wide) == "YS"
    assert choose_freq(narrow) == "D"
    assert len(spend_over_time(
        expenses({"receipt_id": 1, "receipt_date": "2010-08-20"},
                 {"receipt_id": 2, "receipt_date": "2026-08-01"}),
        "GBP")) <= MAX_CHART_BARS


def test_the_timeline_is_scoped_to_one_currency():
    df = expenses({"receipt_id": 1, "total_amount": 450.0, "currency": "USD"},
                  {"receipt_id": 2, "total_amount": 10.0, "currency": "GBP"})
    assert float(spend_over_time(df, "USD", freq="MS")["spend"].sum()) == 450.0


def test_undated_receipts_are_excluded_from_the_timeline():
    df = expenses({"receipt_id": 1, "receipt_date": "2026-08-01",
                   "total_amount": 10.0},
                  {"receipt_id": 2, "receipt_date": "not a date",
                   "total_amount": 90.0})
    assert float(spend_over_time(df, "GBP", freq="MS")["spend"].sum()) == 10.0


# --------------------------------------------------------------------------- #
# The running total
# --------------------------------------------------------------------------- #

def test_the_running_total_accumulates_on_the_date_of_the_rejection():
    """The money was stopped when Amara clicked, not when the meal was eaten."""
    df = expenses({"receipt_id": 1, "receipt_date": "2026-01-05",
                   "total_amount": 100.0, "verdict": "high_risk",
                   "status": "rejected", "decided_at": "2026-03-01T09:00:00+00:00"},
                  {"receipt_id": 2, "receipt_date": "2026-01-06",
                   "total_amount": 50.0, "verdict": "high_risk",
                   "status": "rejected", "decided_at": "2026-04-01T09:00:00+00:00"})
    running = prevented_running_total(df, "GBP")

    assert list(running.index.strftime("%Y-%m-%d")
                ) == ["2026-03-01", "2026-04-01"]
    assert list(running) == [100.0, 150.0]


def test_the_running_total_ends_at_the_tile_figure():
    """The chart and the tile cannot disagree about the same claims."""
    df = expenses({"receipt_id": 1, "total_amount": 100.0, "verdict": "high_risk",
                   "status": "rejected", "decided_at": "2026-03-01T09:00:00+00:00"},
                  {"receipt_id": 2, "total_amount": 50.0, "verdict": "high_risk",
                   "status": "rejected", "decided_at": "2026-04-01T09:00:00+00:00"})

    assert (prevented_running_total(df, "GBP").iloc[-1]
            == spend_summary(df).totals.loc["GBP", "prevented"])


def test_an_undated_rejection_counts_in_the_total_but_not_on_the_curve():
    """It has no x-position, so the curve can legitimately end below the tile.
    The page reports the gap rather than quietly reconciling it."""
    df = expenses({"total_amount": 100.0, "verdict": "high_risk",
                   "status": "rejected", "decided_at": ""})
    summary = spend_summary(df)

    assert summary.totals.loc["GBP", "prevented"] == 100.0
    assert summary.undated_rejections == 1
    assert prevented_running_total(df, "GBP").empty


# --------------------------------------------------------------------------- #
# Through the real loaders
# --------------------------------------------------------------------------- #

def test_rejecting_a_claim_moves_money_from_at_risk_to_prevented(sheet_tabs):
    """End to end through the sheet: seed, reject, recompute. Guards the wiring
    and `update_decision`'s cache invalidation, not only the arithmetic."""
    sheet_tabs["Receipts"].append_row(
        [1, "2026-08-14", "The Ivy", "[]", 264.0, 24.0, "client_entertainment",
         "GBP", "U04ALEX", "", "b.jpg", "pending_review", "high_risk",
         "Over the guideline", "2026-08-14T09:00:00+00:00", "", ""])

    before = spend_summary(data.load_expenses())
    assert before.totals.loc["GBP", "at_risk"] == 264.0
    assert before.totals.loc["GBP", "prevented"] == 0.0

    data.update_decision(1, "rejected")

    after = spend_summary(data.load_expenses())
    assert after.totals.loc["GBP", "at_risk"] == 0.0
    assert after.totals.loc["GBP", "prevented"] == 264.0
