"""E3 — the policy health trend.

The invariant every test here defends: **an unassessed receipt is not a
compliant one**. It is drawn as its own state, and it appears in neither the
numerator nor the denominator of any rate — otherwise a pipeline outage would
render as a compliance collapse, which is the wrong diagnosis and would send
somebody to fix the wrong thing.

`fake_cpi` is used wherever a C4 number is asserted, so the re-priced limits are
deterministic and no test reaches the World Bank.
"""

import pandas as pd
import pytest

from dashboard.policy_health import (CLEARED, MIN_RATE_BASE, NEEDS_REVIEW,
                                     NEVER_ASSESSED, UNRECOGNISED, breakdown,
                                     compliance_trend,
                                     repriced_within_todays_money,
                                     rule_breaches, trend_is_sparse,
                                     verdict_state)
from tests.conftest import expenses


# --------------------------------------------------------------------------- #
# States
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("verdict, expected", [
    ("low_risk", CLEARED),
    ("high_risk", NEEDS_REVIEW),
    (None, NEVER_ASSESSED),
    ("", NEVER_ASSESSED),
    (float("nan"), NEVER_ASSESSED),
    ("banana", UNRECOGNISED),
])
def test_verdict_state(verdict, expected):
    assert verdict_state(verdict) == expected


def test_an_unrecognised_verdict_is_its_own_state_so_the_chart_still_adds_up():
    """`normalise_verdict` passes an unknown value through verbatim, so a typo
    in the sheet is neither of the two verdicts and is not absent either. Left
    unhandled it would vanish from a chart whose whole claim is that its
    arithmetic is honest."""
    trend = compliance_trend(expenses({"verdict": "low_risk"}, {"verdict": "typo"}))
    assert int(trend.iloc[0]["receipts"]) == 2
    assert int(trend.iloc[0][UNRECOGNISED]) == 1


# --------------------------------------------------------------------------- #
# The trend
# --------------------------------------------------------------------------- #

def test_the_trend_buckets_on_when_the_money_was_spent_not_when_it_was_judged():
    """The day C3's gap closes, seven backlog receipts get audited at once. On a
    `created_at` axis that would draw our deployment as a compliance event."""
    trend = compliance_trend(expenses(
        {"receipt_date": "2026-07-31", "created_at": "2026-09-01T09:00:00+00:00",
         "verdict": "low_risk"}))
    assert list(trend.index) == ["2026-07"]


def test_only_months_that_contain_receipts_appear():
    """The live span is sixteen years with two populated months. Reindexing
    across it would produce a chart that is 99% whitespace."""
    trend = compliance_trend(expenses(
        {"receipt_date": "08/20/10 13:12:01"},
        {"receipt_date": "2026-08-01"}))
    assert list(trend.index) == ["2010-08", "2026-08"]


def test_both_live_date_formats_reach_the_trend():
    trend = compliance_trend(expenses(
        {"receipt_date": "2026-08-01", "verdict": "low_risk"},
        {"receipt_date": "08/20/10 13:12:01", "verdict": "low_risk"}))
    assert int(trend["receipts"].sum()) == 2


def test_an_undated_receipt_is_excluded_from_the_trend_rather_than_bucketed():
    trend = compliance_trend(expenses(
        {"receipt_date": "2026-08-01", "verdict": "low_risk"},
        {"receipt_date": "not a date", "verdict": "low_risk"}))
    assert int(trend["receipts"].sum()) == 1


def test_the_sparse_guard_fires_when_the_populated_months_are_years_apart():
    """Two bars sixteen years apart is a composition, not a trend — and the
    chart is still drawn, because the acceptance criterion asks for one."""
    sparse = compliance_trend(expenses({"receipt_date": "08/20/10 13:12:01"},
                                       {"receipt_date": "2026-08-01"}))
    dense = compliance_trend(expenses(
        *({"receipt_id": i, "receipt_date": f"2026-0{i}-15"} for i in range(1, 6))))

    assert trend_is_sparse(sparse)
    assert not trend_is_sparse(dense)


# --------------------------------------------------------------------------- #
# Denominators
# --------------------------------------------------------------------------- #

def test_the_clearance_rate_excludes_unassessed_receipts_from_its_denominator():
    df = expenses(*([{"receipt_id": i, "verdict": "low_risk"} for i in range(1, 5)]
                    + [{"receipt_id": 5, "verdict": "high_risk"}]
                    + [{"receipt_id": i, "verdict": None} for i in range(6, 9)]))
    row = compliance_trend(df).iloc[0]

    assert int(row["receipts"]) == 8
    assert int(row["assessed"]) == 5
    assert row["clearance_rate"] == pytest.approx(0.8)
    assert int(row[NEVER_ASSESSED]) == 3


def test_a_rate_is_suppressed_below_the_minimum_base():
    """One assessed receipt cannot produce a 100% that reads as a trend. The
    floor is ours, not Amara's, which is why it is a named constant."""
    thin = compliance_trend(expenses({"verdict": "low_risk"}))
    assert pd.isna(thin.iloc[0]["clearance_rate"])

    enough = compliance_trend(expenses(
        *({"receipt_id": i, "verdict": "low_risk"} for i in range(1, MIN_RATE_BASE + 1))))
    assert enough.iloc[0]["clearance_rate"] == 1.0


def test_a_category_with_a_single_receipt_gets_counts_but_no_rate():
    table = breakdown(expenses({"category": "travel", "verdict": "high_risk"}),
                      "category")
    assert int(table.loc["TRAVEL", "receipts"]) == 1
    assert pd.isna(table.loc["TRAVEL", "review_rate"])


def test_categories_are_normalised_before_grouping():
    """The sheet holds `Travel` from n8n and `travel` from the audit engine.
    Grouping the raw column splits one category across two rows."""
    table = breakdown(expenses({"receipt_id": 1, "category": "Travel"},
                               {"receipt_id": 2, "category": "travel"},
                               {"receipt_id": 3, "category": "MILEAGE"}),
                      "category")
    assert list(table.index) == ["TRAVEL"]
    assert int(table.loc["TRAVEL", "receipts"]) == 3


def test_the_breakdown_separates_assessed_from_never_assessed():
    """A category that looks clean only because nothing in it was ever audited
    must not pass as compliant."""
    table = breakdown(expenses({"receipt_id": 1, "category": "travel",
                                "verdict": "low_risk"},
                               {"receipt_id": 2, "category": "travel",
                                "verdict": None}),
                      "category")
    assert int(table.loc["TRAVEL", "assessed"]) == 1
    assert int(table.loc["TRAVEL", NEVER_ASSESSED]) == 1


# --------------------------------------------------------------------------- #
# Re-checked rules
# --------------------------------------------------------------------------- #

def _breaches(df):
    return {row["rule"]: (row["breaches"], row["evaluated"])
            for _, row in rule_breaches(df).iterrows()}


def test_the_one_month_cutoff_survives_the_live_mix_of_date_formats(fake_cpi):
    """The exact live shape: a 2010 receipt date parsed tz-naive against a
    2026 Zulu `created_at`. Subtracting those raises unless both are put on one
    clock, and this is the rule producing most of the live chart."""
    df = expenses({"receipt_date": "08/20/10 13:12:01",
                   "created_at": "2026-09-09T12:16:44.931Z"})
    assert _breaches(df)["EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"] == (1, 1)


def test_a_claim_submitted_inside_the_month_is_not_a_breach(fake_cpi):
    df = expenses({"receipt_date": "2026-08-01",
                   "created_at": "2026-08-20T09:00:00+00:00"})
    assert _breaches(df)["EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"] == (0, 1)


def test_the_cutoff_is_not_evaluated_when_the_submission_time_is_missing(fake_cpi):
    """Unknowable is not the same as compliant, and it is not a breach either.
    It drops out of both halves of the fraction."""
    df = expenses({"receipt_date": "2026-08-01", "created_at": ""})
    assert _breaches(df)["EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"] == (0, 0)


def test_the_cfo_threshold_uses_amaras_current_figure(fake_cpi):
    """"The CFO approval used to be over a thousand. It's over two thousand
    now" — so a £1,500 claim is not a CFO-threshold breach."""
    df = expenses({"receipt_id": 1, "total_amount": 2500.0},
                  {"receipt_id": 2, "total_amount": 1500.0})
    assert _breaches(df)["CFO_APPROVAL_THRESHOLD"] == (1, 2)


def test_an_uncapped_category_is_absent_from_the_category_limit_denominator(fake_cpi):
    """Seven of the twelve handbook categories set no numeric ceiling. A travel
    claim belongs in no category-limit fraction at all — not as a pass."""
    df = expenses({"category": "travel", "total_amount": 5000.0})
    breaches = _breaches(df)
    assert breaches["INFLATION_ADJUSTED_LIMIT_EXCEEDED"] == (0, 0)
    assert breaches["OVER_CATEGORY_GUIDELINE"] == (0, 0)


def test_a_claim_over_the_repriced_limit_is_a_breach(fake_cpi):
    """£60 a day of subsistence: over the handbook's £46 and over the same
    figure restated in today's money, so it is a violation on both."""
    df = expenses({"category": "subsistence", "total_amount": 60.0})
    assert _breaches(df)["INFLATION_ADJUSTED_LIMIT_EXCEEDED"] == (1, 1)


def test_a_good_deal_is_counted_as_policy_decay_and_never_as_a_breach(fake_cpi):
    """£50 a day is over the written £46 and inside the re-priced figure. That
    is a stale rule, not overspending, and it is the distinction the brief's
    "Policy Decay" problem is about."""
    df = expenses({"category": "subsistence", "total_amount": 50.0})
    breaches = _breaches(df)

    assert breaches["INFLATION_ADJUSTED_LIMIT_EXCEEDED"] == (0, 1)
    assert breaches["OVER_CATEGORY_GUIDELINE"] == (0, 1)
    assert repriced_within_todays_money(df) == (1, 1)


def test_a_receipt_can_break_more_than_one_rule(fake_cpi):
    """The bars can sum above the receipt count; the page says so, otherwise it
    reads as an arithmetic error."""
    df = expenses({"receipt_date": "2026-01-01",
                   "created_at": "2026-09-01T09:00:00+00:00",
                   "category": "subsistence", "total_amount": 3000.0})
    breaches = _breaches(df)

    assert breaches["EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"][0] == 1
    assert breaches["CFO_APPROVAL_THRESHOLD"][0] == 1
    assert breaches["INFLATION_ADJUSTED_LIMIT_EXCEEDED"][0] == 1


def test_handbook_rules_the_pipeline_does_not_check_are_marked_as_such(fake_cpi):
    """Handbook 2.2 and 8.1 are checked here and nowhere else in the system.
    That gap belongs to the team, not to the employee, so the page has to be
    able to say which rules the live pipeline actually enforces."""
    table = rule_breaches(expenses({"category": "miscellaneous",
                                    "total_amount": 40.0, "line_items": []}))
    enforced = dict(zip(table["rule"], table["enforced"]))

    assert enforced["MISC_JUSTIFICATION_REQUIRED"] is False
    assert enforced["ITEMISED_RECEIPT_REQUIRED"] is False
    assert enforced["CFO_APPROVAL_THRESHOLD"] is True
    assert dict(zip(table["rule"], table["breaches"]))[
        "MISC_JUSTIFICATION_REQUIRED"] == 1


def test_rules_are_ranked_by_count_not_by_rate(fake_cpi):
    """Ranking by rate puts whichever rule was evaluated once at the top of
    "recurring problem areas" every time."""
    df = expenses(
        *([{"receipt_id": i, "receipt_date": "2026-01-01",
            "created_at": "2026-09-01T09:00:00+00:00", "total_amount": 10.0}
           for i in range(1, 6)]
          + [{"receipt_id": 6, "total_amount": 3000.0}]))
    assert rule_breaches(df).iloc[0]["rule"] == "EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"


# --------------------------------------------------------------------------- #
# Degenerate input
# --------------------------------------------------------------------------- #

def test_an_empty_frame_produces_empty_tables_with_the_expected_columns():
    empty = pd.DataFrame()
    assert compliance_trend(empty).empty
    assert rule_breaches(empty).empty
    assert breakdown(empty, "category").empty
    assert repriced_within_todays_money(empty) == (0, 0)


def test_an_unreadable_total_is_not_counted_as_a_pass(fake_cpi):
    df = expenses({"total_amount": "not a number"})
    assert _breaches(df)["CFO_APPROVAL_THRESHOLD"] == (0, 0)
