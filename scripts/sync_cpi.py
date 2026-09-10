#!/usr/bin/env python3
"""Refresh the CPI reference sheet that n8n's agent tool sub-workflow reads.

    python scripts/sync_cpi.py            # pull the World Bank series, write it
    python scripts/sync_cpi.py --dry-run  # show what would be written

Pulls the World Bank's global consumer-price inflation series and writes one row
per year to the **CPI** tab, with both the published annual rate and a chained
price index. n8n reads that tab rather than calling the World Bank itself, so the
workflow has no external dependency at audit time and every run of the agent sees
the same numbers this repo's tests do.

The series gains one value a year, so this only needs re-running when the World
Bank publishes — or on demand before a demo. C2 (AA's scheduled pull) is the
n8n-native version of exactly this; until it exists, run this by hand.

Setup, once: open the CPI spreadsheet (its id lives in `CPI_SPREADSHEET_ID` in
`api/sheets.py`) -> Share -> add the service account's `client_email` from
`service_account.json` as an **Editor**. Without that the write fails with a 403,
even if the sheet is otherwise link-shareable.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.audit import CPI_SERIES_ID, global_inflation_rates  # noqa: E402
from api.sheets import (CPI_SPREADSHEET_ID, CPI_TAB, SPREADSHEET_ID,  # noqa: E402
                        write_cpi_series)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rows without writing to the sheet")
    args = parser.parse_args()

    rates, source = global_inflation_rates()
    if source != "worldbank":
        print("WARNING: the World Bank API could not be reached — this would "
              "write the pinned offline snapshot, not live data. Not writing.\n"
              "         Re-run when you have a connection, or pass --dry-run to "
              "see the snapshot.", file=sys.stderr)
        if not args.dry_run:
            return 1

    target = CPI_SPREADSHEET_ID or SPREADSHEET_ID
    print(f"series : {CPI_SERIES_ID}  ({source})")
    print(f"target : {CPI_TAB} tab of "
          f"https://docs.google.com/spreadsheets/d/{target}/edit")
    print(f"years  : {min(rates)}-{max(rates)}  ({len(rates)} rows)\n")

    level = 100.0
    print(f"  {'year':<6}{'rate %':>10}{'index':>12}")
    for year in sorted(rates):
        print(f"  {year:<6}{rates[year]:>10.4f}{level:>12.4f}")
        level *= 1 + rates[year] / 100

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    written = write_cpi_series(rates, CPI_SERIES_ID, source)
    print(f"\nWrote {written} rows to the {CPI_TAB} tab.")
    print("If this failed with a 403, the service account is not shared on that "
          "spreadsheet — see the setup notes at the top of this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
