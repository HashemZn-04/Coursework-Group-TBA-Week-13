#!/usr/bin/env python3
"""Append additional trend-following "travel" receipts, spread across the
full 36-month window the H1 forecast fits against (2024-01 to 2026-12).

Why: `seed_mock_data.py`'s trend cohort only covers 12 of those 36 months
(2025-09 to 2026-08); the other 24 months carry only its flat, unstructured
`EXTRA_MONTHS` scatter (see that file's module docstring). A linear fit
across all 36 months can then only explain what's happening in a third of
its own history, which is why the H1 forecast's 1-month R^2/RMSE were low
across GBP/USD/EUR alike (investigated in ticket_work/handoff_8.md).

This adds up to `BUDGET` (500) new "travel" receipts per currency, one
target amount per month on a straight line (`BASE_ADD + SLOPE_ADD * i`,
`i` = month index 0..35 from 2024-01), split across ~14 receipts/month with
+-15% jitter so each month's *added* total sits close to the line without
being perfectly flat. Existing rows are untouched — this only appends.

    python scripts/extend_travel_trend.py --dry-run   # preview, nothing written
    python scripts/extend_travel_trend.py             # write to the live sheet
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_mock_data import PROFILES, EXTRA_MONTHS, build_row  # noqa: E402

BUDGET = 500
BASE_ADD, SLOPE_ADD = 100.0, 68.57
JITTER = 0.15

DEFAULT_SEEDS = {"USD": 9001, "GBP": 9002, "EUR": 9003}

# 500 receipts over 36 months: 14 for 32 of them, 13 for the rest -> 500 exactly.
_COUNTS = [14] * 32 + [13] * 4


def generate_currency(currency, seed):
    rng = random.Random(seed)
    merchants = [m for _, ms, _, _ in PROFILES[currency]["travel"] for m in ms]
    rows = []
    for i, month in enumerate(EXTRA_MONTHS):
        target = BASE_ADD + SLOPE_ADD * i
        count = _COUNTS[i]
        per_receipt = target / count
        for _ in range(count):
            amount = round(per_receipt * rng.uniform(1 - JITTER, 1 + JITTER), 2)
            merchant = rng.choice(merchants)
            verdict = "low_risk" if rng.random() < 0.90 else "high_risk"
            rows.append(build_row(rng, month, rng.randint(1, 27), merchant,
                                  amount, "travel", currency, "Fare", verdict))
    assert len(rows) == BUDGET, f"{currency}: {len(rows)} rows, expected {BUDGET}"
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print row counts/totals without writing to the sheet")
    args = parser.parse_args()

    rows = []
    for currency, seed in DEFAULT_SEEDS.items():
        rows.extend(generate_currency(currency, seed))
    rows.sort(key=lambda r: r["created_at"])

    by_currency = {}
    for row in rows:
        by_currency.setdefault(row["currency"], []).append(row["total_amount"])
    print(f"{len(rows)} rows total\n")
    for currency, amounts in by_currency.items():
        print(f"{currency}: {len(amounts)} claims, "
              f"{sum(amounts):,.2f} total, {sum(amounts) / len(amounts):,.2f} avg")

    if args.dry_run:
        print("\n--dry-run: nothing written. Sample rows:")
        for row in rows[:5] + rows[-5:]:
            print(f"  {row['receipt_date']} {row['merchant']:<22} "
                  f"{row['total_amount']:>9,.2f} {row['currency']} "
                  f"{row['verdict']:<10} {row['status']}")
        return 0

    from api.sheets import RECEIPT_HEADERS, receipts_ws, next_id  # noqa: E402

    ws = receipts_ws()
    start_id = next_id(ws, "receipt_id", RECEIPT_HEADERS)
    values = []
    for offset, row in enumerate(rows):
        row["receipt_id"] = start_id + offset
        row["line_items"] = json.dumps(row["line_items"])
        values.append([row.get(h, "") for h in RECEIPT_HEADERS])

    # RAW, not USER_ENTERED — see seed_mock_data.py's comment on the same call:
    # Sheets' locale-aware date parser can silently swap day/month otherwise.
    ws.append_rows(values, value_input_option="RAW")
    print(f"\nWrote {len(rows)} rows: receipt_id {start_id}-{start_id + len(rows) - 1}.")
    print("To undo, delete those rows from the Receipts tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
