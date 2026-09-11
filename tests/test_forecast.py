"""H1 — the 3-month-ahead travel spend forecast.

Two things this file is really testing. First, that the model **refuses by
name** whenever the data cannot carry a forecast — Amara's stated bar is a tool
that fails fast and clearly rather than one that makes her wait and then tells
her nothing. Second, that a month whose claims were never audited is not silently
treated as a month with no spend: zero-filling those would drag the line down
with fabricated data, and on the live sheet that is the majority case, not an
edge case.

No network: `inflation_pct` is passed in, so nothing here reaches the World Bank.
"""

import pytest

from api.forecast import (BASELINE_MONTHS, MIN_HISTORY_MONTHS, forecast_next_month,
                          monthly_spend)
from tests.conftest import expenses


def _history(months, amount=500.0, verdict="low_risk", category="travel"):
    return expenses(*({"receipt_id": i, "receipt_date": f"{m}-15",
                       "total_amount": amount(i) if callable(amount) else amount,
                       "category": category, "verdict": verdict}
                      for i, m in enumerate(months, start=1)))


MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #

def test_no_travel_claims_at_all_refuses_by_name():
    result = forecast_next_month(expenses({"category": "subsistence",
                                           "verdict": "low_risk"}))
    assert result["forecast"] is None
    assert result["reason_code"] == "NO_TRAVEL_SPEND"


def test_unaudited_travel_claims_are_not_counted_as_zero_spend():
    """The live sheet's actual shape: travel spend exists but nothing assessed
    it. Reporting "no travel spend" would be a lie about a receipt sitting in
    the Receipts tab, and zero-filling the month would be worse."""
    result = forecast_next_month(expenses(
        {"receipt_date": "2026-08-01", "total_amount": 450.0,
         "category": "travel", "verdict": None}))

    assert result["reason_code"] == "TRAVEL_SPEND_UNPROCESSED"
    assert "never completed the audit pipeline" in result["detail"]
    assert [row["state"] for row in result["history"]] == ["censored"]


def test_a_censored_month_is_excluded_from_the_fit_rather_than_zeroed():
    """A month in which three flights were submitted and none got a verdict is
    not a month in which nobody flew."""
    rows = [{"receipt_id": i, "receipt_date": f"{m}-15", "total_amount": 500.0,
             "category": "travel", "verdict": "low_risk"}
            for i, m in enumerate(MONTHS[:4], start=1)]
    rows.append({"receipt_id": 9, "receipt_date": "2026-05-15",
                 "total_amount": 900.0, "category": "travel", "verdict": None})
    history = forecast_next_month(expenses(*rows), as_of="2026-05-20")["history"]
    states = {row["month"]: row["state"] for row in history}

    assert states["2026-05"] == "censored"
    assert states["2026-01"] == "observed"


def test_a_month_with_no_travel_claims_at_all_is_a_genuine_zero():
    rows = [{"receipt_id": i, "receipt_date": f"{m}-15", "total_amount": 500.0,
             "category": "travel", "verdict": "low_risk"}
            for i, m in enumerate(["2026-01", "2026-03"], start=1)]
    history = monthly_spend(expenses(*rows))[0]

    assert [row.state for row in history] == ["observed", "empty", "observed"]


def test_a_mixed_currency_history_refuses_rather_than_adding_them_up():
    rows = [{"receipt_id": i, "receipt_date": f"{m}-15", "total_amount": 500.0,
             "category": "travel", "verdict": "low_risk",
             "currency": "GBP" if i % 2 else "USD"}
            for i, m in enumerate(MONTHS, start=1)]
    result = forecast_next_month(expenses(*rows))

    assert result["reason_code"] == "MIXED_CURRENCY_HISTORY"
    assert "Handbook 12.2" in result["detail"]


def test_a_sixteen_year_span_refuses_instead_of_fabricating_190_empty_months():
    result = forecast_next_month(expenses(
        {"receipt_id": 1, "receipt_date": "08/20/10 13:12:01",
         "total_amount": 500.0, "category": "travel", "verdict": "low_risk"},
        {"receipt_id": 2, "receipt_date": "2026-08-01", "total_amount": 500.0,
         "category": "travel", "verdict": "low_risk"}))

    assert result["reason_code"] == "SPAN_TOO_WIDE"
    assert result["history"] == []


def test_too_little_history_refuses_and_names_the_minimum():
    result = forecast_next_month(_history(MONTHS[:MIN_HISTORY_MONTHS - 1]))
    assert result["reason_code"] == "TOO_FEW_MONTHS"
    assert str(MIN_HISTORY_MONTHS) in result["detail"]


def test_every_return_carries_the_same_keys():
    """The page reads the same fields whether or not it got a number."""
    refused = forecast_next_month(expenses({"category": "subsistence"}))
    fitted = forecast_next_month(_history(MONTHS), as_of="2026-06-20")
    assert set(refused) == set(fitted)


# --------------------------------------------------------------------------- #
# The fit
# --------------------------------------------------------------------------- #

def test_a_rising_history_forecasts_3_months_after_the_anchor():
    """The forecast reaches 3 months past the anchor, not the month right
    after the last settled one — the user story is about planning a quarter
    ahead, not describing the past."""
    result = forecast_next_month(
        _history(MONTHS, amount=lambda i: 400.0 + 40 * i), as_of="2026-06-20")

    assert result["forecast_month"] == "2026-09"
    assert result["model"]["slope_per_month"] == pytest.approx(40.0)
    assert result["forecast"] == pytest.approx(760.0)
    assert result["model"]["method"].startswith("sklearn")


def test_the_forecast_reaches_forward_from_today_not_from_the_last_data_point():
    """History ending in April, asked in June: the anchor is June and the
    forecast reaches 3 months past it — September, five steps from the last
    data point — not July, three steps from April."""
    result = forecast_next_month(_history(MONTHS[:4]), as_of="2026-06-20")
    assert result["forecast_month"] == "2026-09"
    assert result["model"]["steps_ahead"] == 5


def test_a_flat_history_forecasts_the_same_number_without_claiming_certainty():
    """A perfect fit has zero residual spread. Reported as-is that becomes a
    zero-width range shown to a CFO as a fact."""
    result = forecast_next_month(_history(MONTHS[:4]), as_of="2026-04-20")

    assert result["forecast"] == pytest.approx(500.0)
    assert result["model"]["r_squared"] is None      # no variance to explain
    assert result["range"]["high"] > result["forecast"] > result["range"]["low"]


def test_a_declining_history_never_forecasts_negative_spend():
    result = forecast_next_month(
        _history(MONTHS[:4], amount=lambda i: 900.0 - 280 * i),
        as_of="2026-06-20")

    assert result["forecast"] >= 0.0
    assert result["range"]["low"] >= 0.0


def test_the_baseline_is_the_trailing_average_qa_will_compare_against():
    """H3 checks the model against "a naive baseline (e.g. simple trailing
    average)", so the module hands that number over rather than making QA
    derive it."""
    result = forecast_next_month(
        _history(MONTHS, amount=lambda i: 100.0 * i), as_of="2026-06-20")

    assert result["baseline"]["months"] == BASELINE_MONTHS
    assert result["baseline"]["value"] == pytest.approx(500.0)   # 400, 500, 600


def test_inflation_is_a_comparator_and_never_changes_the_forecast():
    """The series is annual and about a year in arrears. Folding it into a fit
    over a handful of monthly points would imply a precision that is not there,
    so it uprates the baseline instead — which is what separates "spend is
    rising" from "prices are rising"."""
    with_cpi = forecast_next_month(_history(MONTHS), as_of="2026-06-20",
                                   inflation_pct=3.04)
    without = forecast_next_month(_history(MONTHS), as_of="2026-06-20")

    assert with_cpi["forecast"] == without["forecast"]
    assert without["inflation"] is None
    assert with_cpi["inflation"]["uprated_baseline"] > with_cpi["baseline"]["value"]


def test_the_history_is_returned_so_a_refusal_still_draws_the_actuals():
    """A refusal is not a blank page: whatever history exists is still handed
    back, because Amara asked to see the actuals."""
    rows = [{"receipt_id": i, "receipt_date": f"{m}-15", "total_amount": 500.0,
             "category": "travel", "verdict": None}
            for i, m in enumerate(MONTHS[:2], start=1)]
    result = forecast_next_month(expenses(*rows))

    assert result["forecast"] is None
    assert len(result["history"]) == 2


def test_travel_aliases_are_folded_in_before_aggregating():
    """`normalise_category` already folds MILEAGE and TRAVEL_RAIL into TRAVEL;
    re-implementing that here would let the two drift."""
    rows = [{"receipt_id": i, "receipt_date": f"{m}-15", "total_amount": 500.0,
             "category": c, "verdict": "low_risk"}
            for i, (m, c) in enumerate(
                zip(MONTHS, ["travel", "MILEAGE", "Travel (Rail)", "travel_air",
                             "travel", "travel"]), start=1)]
    result = forecast_next_month(expenses(*rows), as_of="2026-06-20")

    assert result["forecast"] is not None
    assert result["model"]["months_fitted"] == 6


def test_an_empty_sheet_refuses_without_raising():
    import pandas as pd
    assert forecast_next_month(pd.DataFrame())["reason_code"] == "NO_TRAVEL_SPEND"
