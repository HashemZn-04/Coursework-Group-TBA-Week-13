#!/usr/bin/env python3
"""
    python scripts/h1_demo.py
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.forecast import (BASELINE_MONTHS, MIN_HISTORY_MONTHS,  # noqa: E402
                          forecast_next_month)
from api.summary import format_money  # noqa: E402
from dashboard.data import parse_dates, parse_timestamps  # noqa: E402

#: Held fixed rather than read from the clock, so the printed output is the same
#: artifact every time it is run.
AS_OF = "2026-09-10"

#: Latest published global annual inflation (World Bank world aggregate, 2025).
INFLATION_PCT = 3.0414132155654


def receipts(rows):
    df = pd.DataFrame(rows, columns=[
        "receipt_id", "receipt_date", "merchant", "total_amount", "category",
        "currency", "submitter", "created_at", "verdict"])
    df["date"] = parse_dates(df["receipt_date"])
    df["submitted_at"] = parse_timestamps(df["created_at"])
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = df["receipt_id"].astype("Int64")
    df["line_items"] = [[] for _ in range(len(df))]
    df["reason"] = None
    return df


def history(amounts, category="travel", currency="GBP", verdict="low_risk",
            start_month=1):
    return receipts([
        (index, f"2026-{start_month + offset:02d}-15", "Delta Airlines", amount,
         category, currency, "j.chen", "2026-09-01T09:00:00+00:00", verdict)
        for offset, (index, amount) in enumerate(enumerate(amounts, start=1))])


#: (label, frame, expected reason_code — None means "a forecast is produced")
SCENARIOS = [
    ("The live sheet's own shape: one travel claim, never audited",
     receipts([(1, "2026-08-01", "Delta Airlines", 450.0, "travel", "USD",
                "j.chen", "2026-08-01T12:00:00Z", None)]),
     "TRAVEL_SPEND_UNPROCESSED"),

    ("No travel claims at all",
     receipts([(1, "2026-08-01", "Pret A Manger", 9.20, "subsistence", "GBP",
                "u.one", "2026-08-01T12:00:00Z", "low_risk")]),
     "NO_TRAVEL_SPEND"),

    (f"Three assessed months — one short of the {MIN_HISTORY_MONTHS} the model "
     f"will fit",
     history([500.0, 520.0, 540.0]),
     "TOO_FEW_MONTHS"),

    ("Six months of rising travel spend — the working case",
     history([440.0, 480.0, 520.0, 560.0, 600.0, 640.0]),
     None),

    ("Six flat months — no trend to find, and no false certainty either",
     history([500.0] * 6),
     None),

    ("Six declining months, extrapolating below zero",
     history([900.0, 760.0, 620.0, 480.0, 340.0, 200.0]),
     None),

    ("A history that mixes GBP and USD",
     pd.concat([history([500.0] * 3), history([500.0] * 3, currency="USD",
                                              start_month=4)],
               ignore_index=True),
     "MIXED_CURRENCY_HISTORY"),

    ("The SROIE sample's sixteen-year span",
     receipts([(1, "08/20/10 13:12:01", "Delta", 500.0, "travel", "GBP",
                "j.chen", "2026-09-01T09:00:00+00:00", "low_risk"),
               (2, "2026-08-01", "Delta", 500.0, "travel", "GBP", "j.chen",
                "2026-09-01T09:00:00+00:00", "low_risk")]),
     "SPAN_TOO_WIDE"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print("H1 — 3-month-ahead travel spend forecast")
    print("=" * 72)
    print(f"\nas of {AS_OF} · fits at least {MIN_HISTORY_MONTHS} assessed "
          f"months · naive baseline is the trailing {BASELINE_MONTHS}-month "
          f"mean\ninflation comparator: {INFLATION_PCT:.4f}% a year "
          f"(World Bank world aggregate, latest published year)\n")

    failures = []
    for label, frame, expected in SCENARIOS:
        print(f"  {label}")
        result = forecast_next_month(frame, as_of=AS_OF,
                                     inflation_pct=INFLATION_PCT)
        code = result["reason_code"]
        ok = code == expected
        if not ok:
            failures.append((label, expected, code))

        if result["forecast"] is None:
            print(f"    -> no forecast: {code}  "
                  f"{'OK' if ok else f'MISMATCH (expected {expected})'}")
            print(f"       {result['detail']}")
        else:
            money = result["currency"]
            print(f"    -> {format_money(result['forecast'], money)} for "
                  f"{result['forecast_month']}  "
                  f"{'OK' if ok else f'MISMATCH (expected {expected})'}")
            print(f"       range {format_money(result['range']['low'], money)} "
                  f"– {format_money(result['range']['high'], money)} · "
                  f"naive {BASELINE_MONTHS}-month mean "
                  f"{format_money(result['baseline']['value'], money)} · "
                  f"uprated for inflation "
                  f"{format_money(result['inflation']['uprated_baseline'], money)}")
            model = result["model"]
            print(f"       {model['method']}: slope "
                  f"{model['slope_per_month']:+,.2f}/month, "
                  f"intercept {model['intercept']:,.2f}, "
                  f"r² {model['r_squared']}, RMSE "
                  f"{format_money(model['rmse'], money)}, residual sd "
                  f"{model['residual_std']:,.2f}, "
                  f"{model['months_fitted']} months fitted, "
                  f"{model['steps_ahead']} step(s) ahead")
            print(f"       {result['detail']}")
        print()

    if failures:
        for label, expected, actual in failures:
            print(f"FAIL: {label}\n      expected {expected}, got {actual}")
        return 1

    print("All scenarios behaved as stated.")
    print("\nMethod: ordinary least squares over monthly totals "
          "(sklearn.linear_model.LinearRegression), fitted only to months whose "
          "claims completed the audit pipeline. A month with no travel claims is "
          "a real zero; a month whose claims were never audited is not, and is "
          "excluded rather than zero-filled. The range is ±1.96 residual "
          "standard deviations with the half-width floored, so a perfectly "
          "linear history cannot report itself as certainty. Inflation is a "
          "comparator on the baseline, not a term in the fit — the series is "
          "annual and about a year in arrears.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
