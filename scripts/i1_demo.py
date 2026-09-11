#!/usr/bin/env python3
"""
    python scripts/i1_demo.py
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.clusters import (AMOUNT_TOLERANCE_ABS, AMOUNT_TOLERANCE_PCT,  # noqa: E402
                          DATE_WINDOW_DAYS, IMMATERIAL, REVIEW, find_patterns)
from api.summary import format_money  # noqa: E402
from dashboard.data import parse_dates, parse_timestamps  # noqa: E402


def receipts(rows):
    df = pd.DataFrame(rows, columns=[
        "receipt_id", "receipt_date", "merchant", "total_amount", "category",
        "currency", "submitter"])
    df["date"] = parse_dates(df["receipt_date"])
    df["created_at"] = "2026-09-09T12:00:00Z"
    df["submitted_at"] = parse_timestamps(df["created_at"])
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = df["receipt_id"].astype("Int64")
    df["line_items"] = [[] for _ in range(len(df))]
    df["verdict"] = None
    df["reason"] = None
    df["status"] = "pending"
    return df


#: Verbatim from the live spreadsheet on 2026-09-09 (receipt_ids 2-8).
LIVE_ROWS = [
    (2, "08/20/10 13:12:01", "WAL*MART", 5.11, "subsistence", "USD", "U0B4SSV8YJE"),
    (3, "08/20/10 13:12:01", "WAL*MART", 5.11, "accommodation", "USD", "U0B4SSV8YJE"),
    (4, "08/20/10 13:12:01", "WAL-MART", 5.11, "subsistence", "USD", "U0B5M5WBV16"),
    (5, "08/20/10 13:12:01", "WAL-MART", 5.11, "subsistence", "USD", "U0B5M5WBV16"),
    (6, "08/20/10 13:12:01", "Walmart", 5.11, "subsistence", "USD", "U0B4SSV8YJE"),
    (7, "08/20/10 13:12:01", "WAL*MART", 5.11, "subsistence", "USD", "U0B5M5WBV16"),
    (8, "08/20/10 13:12:01", "WAL*MART", 5.11, "subsistence", "USD", "U0B5M5WBV16"),
]

#: (label, frame, expected severities in order — [] means nothing is grouped)
SCENARIOS = [
    ("The live sheet: seven WAL*MART claims, one date, two submitters",
     receipts(LIVE_ROWS), [REVIEW]),

    ("Split bill: three colleagues, one restaurant, one evening, £140 each",
     receipts([(i, "2026-08-03", "Hawksmoor Restaurant", 140.0,
                "client_entertainment", "GBP", f"u.{i}") for i in (1, 2, 3)]),
     [REVIEW]),

    ("I3: two colleagues buying lunch at the same place on the same morning",
     receipts([(1, "2026-08-03", "Pret A Manger", 2.80, "subsistence", "GBP", "u.one"),
               (2, "2026-08-03", "Pret-A-Manger", 3.10, "subsistence", "GBP", "u.two")]),
     [IMMATERIAL]),

    ("I3: a team using one approved vendor month after month",
     receipts([(i, f"2026-{i:02d}-05", "Regus Serviced Offices", 300.0,
                "office_supplies", "GBP", f"u.{i}") for i in range(1, 6)]),
     []),

    ("I3: same hotel, same night, genuinely different room rates",
     receipts([(1, "2026-08-03", "Hilton Manchester", 110.0, "accommodation",
                "GBP", "u.one"),
               (2, "2026-08-03", "Hilton Manchester", 460.0, "accommodation",
                "GBP", "u.two")]),
     []),

    ("I3: unreadable merchant names, which must never group with each other",
     receipts([(1, "2026-08-03", "", 100.0, "other", "GBP", "u.one"),
               (2, "2026-08-03", "The Ltd", 100.0, "other", "GBP", "u.two")]),
     []),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print("I1 — Syndicated Spending detection")
    print("=" * 72)
    print(f"\nClaims group only with claims from the same merchant and currency, "
          f"within\n{AMOUNT_TOLERANCE_PCT:.0%} (or {AMOUNT_TOLERANCE_ABS:.2f}) "
          f"on amount and {DATE_WINDOW_DAYS} days on date. Grouping is DBSCAN "
          f"over that\ndistance; the distance itself is defined in named units "
          f"so the basis is readable.\n")

    failures = []
    for label, frame, expected in SCENARIOS:
        print(f"  {label}")
        found = find_patterns(frame)
        actual = [pattern.severity for pattern in found]
        ok = actual == expected
        if not ok:
            failures.append((label, expected, actual))

        if not found:
            print(f"    -> nothing grouped  "
                  f"{'OK' if ok else f'MISMATCH (expected {expected})'}")
        for pattern in found:
            print(f"    -> {pattern.pattern} · {pattern.severity} · "
                  f"{pattern.receipts} claims · "
                  f"{format_money(pattern.total, pattern.currency)}  "
                  f"{'OK' if ok else f'MISMATCH (expected {expected})'}")
            print(f"       {pattern.basis}")
            if pattern.exact_repeats:
                print("       exact repeats: " + ", ".join(
                    f"{who} x{n}" for who, n in pattern.exact_repeats.items()))
        print()

    if failures:
        for label, expected, actual in failures:
            print(f"FAIL: {label}\n      expected {expected}, got {actual}")
        return 1

    print("All scenarios behaved as stated.")
    print("\nThe first two are raised for review; the last four are the "
          "legitimate patterns QA's I3 ticket constructs, and none of them "
          "reaches the queue. Handbook 10.2 is explicit that \"the presence of "
          "any such pattern does not, on its own, establish misconduct\" — this "
          "is a prompt to look, and the dashboard records that Amara looked "
          "without approving anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
