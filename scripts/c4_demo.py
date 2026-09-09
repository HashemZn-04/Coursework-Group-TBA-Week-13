#!/usr/bin/env python3
"""C4 (MCP-27) acceptance evidence — the constructed example, run live.

    python scripts/c4_demo.py                       # in-process, live FRED call
    python scripts/c4_demo.py --api http://localhost:5000
                                                    # through the running API,
                                                    # printing request/response

The acceptance criterion asks for "a receipt priced above a static old limit but
within current inflation-adjusted benchmark [...] correctly classified as
acceptable (and vice versa) — demonstrated with at least one constructed
example". This runs five, prints what CPI figures were used and where they came
from, and exits non-zero if any of them classifies wrongly — so it is evidence
when it passes and a failing check when it does not.

Paste the output into the C4 Jira ticket. It is the artifact.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.audit import contextual_validation  # noqa: E402
from api.policy import CATEGORY_LIMITS  # noqa: E402

#: (label, total, category, attendees, expected assessment)
EXAMPLES = [
    ("Client dinner, one head, £88 — the headline case: over the 2019 £75 "
     "figure, under the same figure re-priced to today",
     88.00, "CLIENT_ENTERTAINMENT", 1, "GOOD_DEAL"),
    ("The same dinner at £120 a head — over the limit on any measure",
     120.00, "CLIENT_ENTERTAINMENT", 1, "OVER_GUIDELINE"),
    ("£300 client dinner for four — £75 a head, inside the written limit",
     300.00, "CLIENT_ENTERTAINMENT", 4, "WITHIN_LIMIT"),
    ("£50 day's subsistence — over the £46 daily total, inside the re-priced one",
     50.00, "SUBSISTENCE", 1, "GOOD_DEAL"),
    ("£60 day's subsistence — over both, so a real violation",
     60.00, "SUBSISTENCE", 1, "POLICY_VIOLATION"),
]


def run_locally(total, category, attendees):
    return contextual_validation(total, category, units=attendees)


def run_against_api(base_url, total, category, attendees):
    import requests

    payload = {"total": total, "category": category, "attendee_count": attendees}
    print(f"    $ curl -s -X POST {base_url}/api/validate \\")
    print(f"        -H 'Content-Type: application/json' \\")
    print(f"        -d '{json.dumps(payload)}'")
    response = requests.post(f"{base_url}/api/validate", json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", help="base URL of a running api/app.py; omit to "
                                      "evaluate in-process")
    args = parser.parse_args()

    print("C4 — Contextual Validation, inflation-aware (MCP-27)")
    print("=" * 72)
    print("\nHandbook limits in play, and when each was last set:\n")
    for name, limit in CATEGORY_LIMITS.items():
        kind = "hard limit" if limit.hard else "guideline"
        print(f"  {name:<26} £{limit.amount:>7,.2f} {limit.basis:<10} "
              f"set {limit.base_period[:7]}  ({kind})")
        print(f"  {'':<26} {limit.source}")

    print("\nConstructed examples:\n")
    failures = []
    for label, total, category, attendees, expected in EXAMPLES:
        print(f"  {label}")
        result = (run_against_api(args.api, total, category, attendees)
                  if args.api else run_locally(total, category, attendees))

        ok = result["assessment"] == expected
        if not ok:
            failures.append((label, expected, result["assessment"]))
        print(f"    -> {result['assessment']}  "
              f"{'OK' if ok else f'MISMATCH (expected {expected})'}")
        print(f"       written limit £{result['static_limit']:,.2f} · "
              f"re-priced £{result['adjusted_limit']:,.2f} · "
              f"x{result['inflation_factor']} · "
              f"£{result['unit_amount']:,.2f} {result['basis']}")
        print(f"       {result['detail']}")
        cpi = result["cpi"]
        print(f"       CPI {cpi['series_id']}: {cpi['base_value']} "
              f"({cpi['base_period'][:7]}) -> {cpi['latest_value']} "
              f"({cpi['latest_period'][:7]}), source: {cpi['source']}")
        print()

    if failures:
        for label, expected, actual in failures:
            print(f"FAIL: {label}\n      expected {expected}, got {actual}")
        return 1

    print("All examples classified as expected.")
    print("\nNote: a 'fallback' CPI source above means FRED could not be reached "
          "and the pinned 2026-09-09 snapshot was used. Set FRED_API_KEY in .env "
          "for a live figure before capturing this as evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
