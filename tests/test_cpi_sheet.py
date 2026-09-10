"""The CPI reference tab n8n's agent tool sub-workflow reads.

The contract that matters to n8n: one row per year, carrying both the published
annual rate and a chained price index, so re-pricing a limit is a lookup of two
rows and one division rather than a calculation the agent has to get right.
"""

from api import sheets
from tests.conftest import GLOBAL_RATES


def test_write_cpi_series_writes_one_row_per_year(sheet_tabs):
    written = sheets.write_cpi_series(GLOBAL_RATES, "WLD.FP.CPI.TOTL.ZG")
    rows = sheet_tabs["CPI"].get_all_records()

    assert written == len(GLOBAL_RATES) == len(rows)
    assert [int(r["year"]) for r in rows] == sorted(GLOBAL_RATES)
    assert rows[0]["series_id"] == "WLD.FP.CPI.TOTL.ZG"
    assert rows[0]["source"] == "worldbank"
    assert rows[0]["fetched_at"]


def test_price_index_is_anchored_at_100_and_compounds(sheet_tabs):
    sheets.write_cpi_series(GLOBAL_RATES, "WLD.FP.CPI.TOTL.ZG")
    rows = sheet_tabs["CPI"].get_all_records()
    index = {int(r["year"]): float(r["price_index"]) for r in rows}

    assert index[min(index)] == 100.0
    # Each year's level is the previous one grown by the previous year's rate.
    for year in sorted(index)[1:]:
        expected = index[year - 1] * (1 + GLOBAL_RATES[year - 1] / 100)
        assert abs(index[year] - expected) < 1e-4


def test_the_index_reproduces_the_engines_own_factor(sheet_tabs):
    """The whole point of publishing the index: n8n dividing two rows must get
    the same answer api.audit computes internally, or the Slack reply and the
    dashboard will disagree about the same receipt."""
    from api.audit import inflation_factor

    sheets.write_cpi_series(GLOBAL_RATES, "WLD.FP.CPI.TOTL.ZG")
    index = {int(r["year"]): float(r["price_index"])
             for r in sheet_tabs["CPI"].get_all_records()}

    last = max(GLOBAL_RATES)
    end_of_series = index[last] * (1 + GLOBAL_RATES[last] / 100)
    from_sheet = end_of_series / index[2019]

    assert abs(from_sheet - inflation_factor("2019-03-01")[0]) < 1e-6


def test_a_refresh_replaces_rather_than_appends(sheet_tabs):
    """The upstream series gets revised, so appending would leave two rows for
    the same year with no way to tell which is current."""
    sheets.write_cpi_series(GLOBAL_RATES, "WLD.FP.CPI.TOTL.ZG")
    sheets.write_cpi_series(GLOBAL_RATES, "WLD.FP.CPI.TOTL.ZG")

    rows = sheet_tabs["CPI"].get_all_records()
    assert len(rows) == len(GLOBAL_RATES)
    assert len({r["year"] for r in rows}) == len(rows)
