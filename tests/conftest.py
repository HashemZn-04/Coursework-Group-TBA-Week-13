"""Shared fixtures.

Nothing here touches the network or the real Google Sheet: FRED is replaced by a
fixed set of observations, and the three sheet tabs by an in-memory worksheet
that behaves the way gspread's does (rows of strings, `get_all_records()`
zipping them against row 1). That is deliberate — these tests need to be
runnable by anyone on the team without credentials, and they need to fail for
logic reasons rather than quota ones.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Real CPIAUCSL observations, pulled 2026-09-09. Using true values keeps the
#: expected numbers in the tests meaningful rather than arbitrary.
CPI_OBSERVATIONS = {
    "2019-03-01": 254.277,
    "2020-04-01": 256.032,
    "2022-01-01": 282.543,
}
CPI_LATEST = ("2026-07-01", 332.813)


@pytest.fixture
def fake_fred(monkeypatch):
    """Deterministic CPI, with the lru_cache cleared either side."""
    from api import audit

    def _observations(params):
        if params.get("sort_order") == "desc":
            return [{"date": CPI_LATEST[0], "value": str(CPI_LATEST[1])}]
        start = params["observation_start"]
        if start not in CPI_OBSERVATIONS:
            raise ValueError(f"unexpected CPI window start {start}")
        return [{"date": start, "value": str(CPI_OBSERVATIONS[start])}]

    monkeypatch.setattr(audit, "_fred_observations", _observations)
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    audit.cpi_for.cache_clear()
    yield audit
    audit.cpi_for.cache_clear()


class FakeWorksheet:
    """Enough of gspread's Worksheet for the code under test.

    Values are stored as strings because that is what Sheets hands back, which
    is exactly the property `_next_id` and the dashboard's numeric coercion have
    to survive.
    """

    def __init__(self, headers, rows=()):
        self.headers = list(headers)
        self.rows = [[("" if cell is None else str(cell)) for cell in row]
                     for row in rows]
        self.updates = []

    def row_values(self, index):
        return self.headers if index == 1 else []

    def get_all_records(self):
        return [dict(zip(self.headers, row)) for row in self.rows]

    def append_row(self, values, value_input_option=None):
        self.rows.append([("" if v is None else str(v)) for v in values])

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.append_row(row)

    def update(self, values=None, range_name=None):
        self.updates.append((range_name, values))

    def find(self, query, in_column=None):
        for offset, row in enumerate(self.rows):
            if row[in_column - 1] == query:
                return type("Cell", (), {"row": offset + 2, "col": in_column})()
        return None

    def update_cell(self, row, col, value):
        self.rows[row - 2][col - 1] = "" if value is None else str(value)


@pytest.fixture(autouse=True)
def no_live_sheets(monkeypatch):
    """Hard stop on reaching the real spreadsheet.

    Learned the hard way: `api.app` binds `receipts_ws` at import time, so
    patching it on `api.sheets` alone left one endpoint talking to the live
    sheet — which showed up as a Google quota error rather than as a failed
    assertion. This makes that mistake fail loudly and instantly instead.
    """
    from api import sheets as api_sheets
    from dashboard import data as dashboard_data

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "a test tried to open the live Google Sheet — patch the worksheet "
            "accessor on every module that imported it, api.app included")

    monkeypatch.setattr(api_sheets, "client", refuse)
    monkeypatch.setattr(dashboard_data, "_client", refuse)


@pytest.fixture
def sheet_tabs(monkeypatch):
    """Patch every worksheet accessor in all three modules at once."""
    from api import app as api_app
    from api import sheets as api_sheets
    from dashboard import data as dashboard_data

    tabs = {
        "Receipts": FakeWorksheet(api_sheets.RECEIPT_HEADERS),
        "Verdicts": FakeWorksheet(api_sheets.VERDICT_HEADERS),
        "Decisions": FakeWorksheet(api_sheets.DECISION_HEADERS),
        "Benchmarks": FakeWorksheet(api_sheets.BENCHMARK_HEADERS),
    }
    accessors = {"receipts_ws": "Receipts", "verdicts_ws": "Verdicts",
                 "decisions_ws": "Decisions", "benchmarks_ws": "Benchmarks"}
    for module in (api_sheets, dashboard_data, api_app):
        for accessor, tab_name in accessors.items():
            if hasattr(module, accessor):
                monkeypatch.setattr(module, accessor,
                                    lambda tab=tabs[tab_name]: tab, raising=True)
    return tabs
