#!/usr/bin/env python3
"""
    python scripts/seed_mock_data.py --dry-run   # preview, nothing written
    python scripts/seed_mock_data.py             # write to the live sheet
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SUBMITTERS = ["j.chen", "s.khan", "r.taylor", "a.mensah", "l.ivanova"]

MONTHS = ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02",
          "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]

# One profile per currency: region-appropriate merchants, its own trip-count
# trend, kept fully independent so tuning one never shifts another's numbers.
PROFILES = {
    "GBP": {
        "travel_trend": (5.0, 0.35),
        "travel": [
            (0.26, ["Uber", "Addison Lee", "TfL Contactless"], 8, 45),
            (0.34, ["Trainline", "LNER", "Great Western Railway"], 25, 140),
            (0.32, ["EasyJet", "British Airways"], 60, 320),
            (0.04, ["National Express"], 15, 45),
            (0.04, ["British Airways"], 350, 850),
        ],
        "accommodation": [
            (0.30, ["Premier Inn"], 59, 95),
            (0.25, ["Travelodge"], 55, 89),
            (0.25, ["ibis London"], 79, 125),
            (0.15, ["Hilton Manchester", "Hilton Birmingham"], 110, 210),
            (0.05, ["Marriott"], 140, 280),
        ],
        "subsistence": [
            (0.25, ["Pret A Manger"], 4, 12),
            (0.20, ["Costa Coffee"], 3, 7),
            (0.15, ["Starbucks"], 3, 8),
            (0.15, ["Leon"], 6, 14),
            (0.15, ["Wagamama"], 12, 28),
            (0.10, ["Team lunch"], 15, 40),
        ],
        "client_entertainment": [
            (0.30, ["The Ivy"], 55, 140),
            (0.30, ["Hawksmoor"], 60, 150),
            (0.25, ["Dishoom"], 35, 85),
            (0.15, ["The Delaunay"], 50, 120),
        ],
    },
    "USD": {
        "travel_trend": (3.0, 0.65),
        "travel": [
            (0.24, ["Uber", "Lyft"], 9, 48),
            (0.20, ["Amtrak"], 30, 150),
            (0.36, ["Delta Airlines", "American Airlines", "United Airlines"], 70, 340),
            (0.10, ["Hertz"], 45, 120),
            (0.10, ["Delta Airlines"], 380, 900),
        ],
        "accommodation": [
            (0.30, ["Holiday Inn"], 65, 105),
            (0.25, ["Courtyard by Marriott"], 90, 140),
            (0.20, ["Marriott"], 130, 240),
            (0.15, ["Hilton"], 120, 260),
            (0.10, ["The Westin"], 180, 320),
        ],
        "subsistence": [
            (0.25, ["Starbucks"], 4, 10),
            (0.20, ["Chipotle"], 8, 15),
            (0.20, ["Panera Bread"], 7, 16),
            (0.15, ["Sweetgreen"], 10, 18),
            (0.20, ["Team lunch"], 15, 45),
        ],
        "client_entertainment": [
            (0.30, ["The Capital Grille"], 60, 150),
            (0.30, ["Nobu"], 70, 180),
            (0.25, ["Smith & Wollensky"], 55, 140),
            (0.15, ["STK Steakhouse"], 60, 150),
        ],
    },
    "EUR": {
        "travel_trend": (2.5, 0.65),
        "travel": [
            (0.22, ["Uber", "FlixBus"], 8, 42),
            (0.34, ["Deutsche Bahn", "SNCF", "Eurostar"], 30, 160),
            (0.34, ["Lufthansa", "Air France"], 65, 330),
            (0.10, ["Lufthansa"], 360, 880),
        ],
        "accommodation": [
            (0.30, ["ibis"], 60, 98),
            (0.25, ["Novotel"], 85, 130),
            (0.25, ["NH Hotels"], 95, 170),
            (0.15, ["Meliá"], 120, 230),
            (0.05, ["Steigenberger"], 150, 290),
        ],
        "subsistence": [
            (0.25, ["Café Central"], 4, 11),
            (0.20, ["Starbucks"], 3, 8),
            (0.20, ["Pret A Manger"], 5, 12),
            (0.20, ["Brasserie Lipp"], 12, 26),
            (0.15, ["Team lunch"], 15, 42),
        ],
        "client_entertainment": [
            (0.30, ["Restaurant Tim Raue"], 65, 160),
            (0.30, ["Brasserie Lipp"], 55, 130),
            (0.25, ["Le Comptoir"], 45, 110),
            (0.15, ["La Coupole"], 50, 120),
        ],
    },
}


def weighted_pick(rng, table):
    r = rng.random()
    cum = 0.0
    for weight, merchants, low, high in table:
        cum += weight
        if r <= cum:
            return rng.choice(merchants), round(rng.uniform(low, high), 2)
    _, merchants, low, high = table[-1]
    return rng.choice(merchants), round(rng.uniform(low, high), 2)


def travel_trip_count(rng, month_index, month_label, base, slope):
    n = base + slope * month_index + rng.uniform(-0.6, 0.6)
    if month_label == "2025-12":
        n = max(n * 0.7, 2)  # holiday slowdown, not a full stop
    if month_label == "2026-03":
        n += 2  # March client offsite
    return max(2, round(n))


def days_in_month(month):
    year, mon = (int(p) for p in month.split("-"))
    return 29 if mon == 2 and year % 4 == 0 else \
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mon - 1]


def stamp(month, day, hour):
    return f"{month}-{day:02d}T{hour:02d}:00:00+00:00"


def build_row(rng, month, day, merchant, amount, category, currency,
             item_label, verdict):
    max_day = days_in_month(month)
    year, mon = month.split("-")
    receipt_date = f"{day:02d}/{mon}/{year}"
    submit_day = min(day + rng.randint(0, 3), max_day)
    created_at = stamp(month, submit_day, rng.randint(8, 18))

    status, decided_at, verdict_reason = "approved", "", (
        "Passed every policy check and was approved automatically. "
        "No human review was required.")
    if verdict == "high_risk":
        outcome = rng.random()
        if outcome < 0.35:
            status = "pending_review"
            verdict_reason = ("Flagged for review: over the category's "
                              "guideline figure once adjusted for inflation.")
        else:
            decide_day = min(submit_day + rng.randint(1, 4), max_day)
            decided_at = stamp(month, decide_day, rng.randint(8, 18))
            if outcome < 0.85:
                status = "approved"
                verdict_reason = ("Reviewed and approved: over guideline but "
                                  "judged reasonable in context.")
            else:
                status = "rejected"
                verdict_reason = ("Reviewed and rejected: over the category's "
                                  "guideline figure with no business "
                                  "justification given.")

    return {
        "receipt_date": receipt_date, "merchant": merchant,
        "line_items": [{"description": item_label, "amount": amount, "quantity": 1}],
        "total_amount": amount, "tax": 0, "category": category, "currency": currency,
        "submitter": rng.choice(SUBMITTERS), "submitter_id": "",
        "raw_file_reference": f"{merchant.lower().replace(' ', '-')}-{receipt_date.replace('/', '-')}.jpg",
        "status": status, "verdict": verdict, "verdict_reason": verdict_reason,
        "created_at": created_at, "updated_at": decided_at or created_at,
        "decided_at": decided_at,
    }


def generate_currency(currency, seed):
    profile = PROFILES[currency]
    base, slope = profile["travel_trend"]
    rng = random.Random(seed)
    rows = []

    for i, month in enumerate(MONTHS):
        for _ in range(travel_trip_count(rng, i, month, base, slope)):
            merchant, amount = weighted_pick(rng, profile["travel"])
            verdict = "high_risk" if rng.random() < 0.08 else "low_risk"
            rows.append(build_row(rng, month, rng.randint(1, 27), merchant,
                                  amount, "travel", currency, "Fare", verdict))

    for month in MONTHS:
        for _ in range(rng.choice([1, 1, 2])):
            merchant, amount = weighted_pick(rng, profile["accommodation"])
            verdict = "high_risk" if rng.random() < 0.08 else "low_risk"
            rows.append(build_row(rng, month, rng.randint(1, 27), merchant,
                                  amount, "accommodation", currency, "Room", verdict))

        for _ in range(rng.randint(4, 9)):
            merchant, amount = weighted_pick(rng, profile["subsistence"])
            rows.append(build_row(rng, month, rng.randint(1, 27), merchant,
                                  amount, "subsistence", currency, "Meal", "low_risk"))

        for _ in range(rng.choice([1, 1, 2])):
            merchant, amount = weighted_pick(rng, profile["client_entertainment"])
            verdict = "high_risk" if rng.random() < 0.20 else "low_risk"
            rows.append(build_row(rng, month, rng.randint(1, 27), merchant,
                                  amount, "client_entertainment", currency,
                                  "Client dinner", verdict))

    return rows


def generate(seeds):
    rows = []
    for currency, seed in seeds.items():
        rows.extend(generate_currency(currency, seed))
    rows.sort(key=lambda r: r["created_at"])
    return rows


DEFAULT_SEEDS = {"GBP": 102, "USD": 18, "EUR": 26}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rows without writing to the sheet")
    parser.add_argument("--seed-gbp", type=int, default=DEFAULT_SEEDS["GBP"])
    parser.add_argument("--seed-usd", type=int, default=DEFAULT_SEEDS["USD"])
    parser.add_argument("--seed-eur", type=int, default=DEFAULT_SEEDS["EUR"])
    args = parser.parse_args()
    seeds = {"GBP": args.seed_gbp, "USD": args.seed_usd, "EUR": args.seed_eur}

    rows = generate(seeds)
    by_currency = {}
    by_category = {}
    for row in rows:
        by_currency.setdefault(row["currency"], []).append(row["total_amount"])
        by_category.setdefault((row["currency"], row["category"]), []).append(row["total_amount"])

    print(f"{len(rows)} rows total\n")
    for currency, amounts in by_currency.items():
        print(f"{currency}: {len(amounts)} claims")
        for (cur, cat), amts in by_category.items():
            if cur == currency:
                print(f"    {cat:<22} {len(amts):>3} claims  "
                      f"{sum(amts):>10,.2f} total  {sum(amts) / len(amts):>7,.2f} avg")

    if args.dry_run:
        print("\n--dry-run: nothing written. Sample rows:")
        for row in rows[:6] + rows[len(rows) // 2:len(rows) // 2 + 6] + rows[-6:]:
            print(f"  {row['receipt_date']} {row['merchant']:<22} "
                  f"{row['total_amount']:>9,.2f} {row['currency']} {row['category']:<20} "
                  f"{row['verdict']:<10} {row['status']}")
        return 0

    from api.sheets import RECEIPT_HEADERS, receipts_ws, next_id  # noqa: E402

    ws = receipts_ws()
    start_id = next_id(ws, "receipt_id")
    values = []
    for offset, row in enumerate(rows):
        row["receipt_id"] = start_id + offset
        row["line_items"] = json.dumps(row["line_items"])
        values.append([row.get(h, "") for h in RECEIPT_HEADERS])

    # RAW, not USER_ENTERED: Sheets' smart date detection reads an ambiguous
    # DD/MM/YYYY string (day <= 12) using its own locale and can silently
    # swap day and month — confirmed by writing "05/01/2026" and reading back
    # "1/5/26" (1 May, not 5 January) under USER_ENTERED. RAW stores the
    # literal text; numeric columns still come back as numbers regardless.
    ws.append_rows(values, value_input_option="RAW")
    print(f"\nWrote {len(rows)} rows: receipt_id {start_id}-{start_id + len(rows) - 1}.")
    print("To undo, delete those rows from the Receipts tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
