"""Shared fixtures.

Nothing here touches the network or the real Google Sheet: the World Bank
inflation series is replaced by a fixed set of rates, and the three sheet tabs by
an in-memory worksheet
that behaves the way gspread's does (rows of strings, `get_all_records()`
zipping them against row 1). That is deliberate — these tests need to be
runnable by anyone on the team without credentials, and they need to fail for
logic reasons rather than quota ones.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGES = ROOT / "pages"


def expenses(*rows) -> pd.DataFrame:
    """A frame shaped exactly like `dashboard.data.load_expenses()` returns one.

    The analytics modules (`dashboard.spend`, `dashboard.policy_health`,
    `api.forecast`, `api.clusters`) are pure functions over that frame, so most
    of their tests want to state a handful of receipts rather than round-trip
    rows through the fake worksheet. This keeps the derived columns — `date`,
    `submitted_at`, `total`, the Int64 `receipt_id` — parsed the same way the
    real loader parses them, so a test cannot accidentally hand the code a
    cleaner frame than production produces.

    Each row is a dict; anything omitted takes the default below.
    """
    from dashboard.data import parse_dates, parse_timestamps

    defaults = {"receipt_id": None, "receipt_date": "2026-08-01",
                "merchant": "Merchant", "line_items": [], "total_amount": 10.0,
                "tax": 0, "category": "travel", "currency": "GBP",
                "submitter": "u.one", "raw_file_reference": "f.jpg",
                "status": "pending_review",
                "created_at": "2026-08-01T09:00:00+00:00", "updated_at": "",
                "verdict": None, "verdict_reason": None, "decided_at": ""}
    built = []
    for index, row in enumerate(rows, start=1):
        merged = {**defaults, **row}
        merged.setdefault("receipt_id", index)
        if merged["receipt_id"] is None:
            merged["receipt_id"] = index
        built.append(merged)

    df = pd.DataFrame(built)
    df["date"] = parse_dates(df["receipt_date"])
    df["submitted_at"] = parse_timestamps(df["created_at"])
    df["decided_at"] = parse_timestamps(df["decided_at"])
    df["total"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_id"] = pd.to_numeric(df["receipt_id"],
                                     errors="coerce").astype("Int64")
    return df


#: Real World Bank world-aggregate inflation rates (%), pulled 2026-09-09.
#: Using true values keeps the expected numbers meaningful rather than arbitrary.
GLOBAL_RATES = {
    2015: 1.43702380935655, 2016: 1.59691227583204, 2017: 2.22314331448899,
    2018: 2.44258329692817, 2019: 2.20607305781525, 2020: 1.90509722047501,
    2021: 3.47540320289875, 2022: 8.08169507021982, 2023: 5.79944107391962,
    2024: 3.01447576977999, 2025: 3.0414132155654,
}


def _clear_cpi_caches(audit):
    """Clear whichever of these are still real lru_cache-wrapped functions.

    The fixture below replaces `global_inflation_rates` with a plain lambda, and
    monkeypatch does not restore it until after this fixture's teardown — so on
    the way out one of the two has no `cache_clear` at all.
    """
    for fn in (audit.cpi_for, audit.global_inflation_rates):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


@pytest.fixture
def fake_cpi(monkeypatch):
    """Deterministic global inflation, with the caches cleared either side."""
    from api import audit

    _clear_cpi_caches(audit)      # before patching, while both are still real
    monkeypatch.setattr(audit, "global_inflation_rates",
                        lambda: (dict(GLOBAL_RATES), "worldbank"))
    audit.cpi_for.cache_clear()
    yield audit
    _clear_cpi_caches(audit)


class FakeWorksheet:
    """Enough of gspread's Worksheet for the code under test.

    Values are stored as strings because that is what Sheets hands back, which
    is exactly the property `next_id` and the dashboard's numeric coercion have
    to survive.
    """

    def __init__(self, headers, rows=()):
        self.headers = list(headers)
        self.rows = [[("" if cell is None else str(cell)) for cell in row]
                     for row in rows]
        self.updates = []

    def row_values(self, index):
        return self.headers if index == 1 else []

    def get_all_records(self, expected_headers=None):
        # `expected_headers` only changes gspread's duplicate-header check on
        # the real API; the fake's headers are never duplicated, so it is
        # accepted (production code passes it) and otherwise ignored.
        return [dict(zip(self.headers, row)) for row in self.rows]

    def append_row(self, values, value_input_option=None):
        self.rows.append([("" if v is None else str(v)) for v in values])

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.append_row(row)

    def update(self, values=None, range_name=None, value_input_option=None):
        self.updates.append((range_name, values))
        # A write anchored at A1 with a header row is a full-table replace,
        # which is what write_cpi_series does.
        if range_name == "A1" and values and values[0] == self.headers:
            self.rows = [[("" if c is None else str(c)) for c in row]
                         for row in values[1:]]

    def clear(self):
        self.rows = []

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
    monkeypatch.setattr(dashboard_data, "client", refuse)

    # The dashboard's loaders are st.cache_data-wrapped to stay inside the
    # Sheets read quota, which would otherwise leak one test's rows into the
    # next.
    for loader in (dashboard_data.load_receipts,
                   dashboard_data.load_cluster_reviews):
        loader.clear()


@pytest.fixture
def sheet_tabs(monkeypatch):
    """Patch every worksheet accessor in all three modules at once."""
    from api import app as api_app
    from api import sheets as api_sheets
    from dashboard import data as dashboard_data

    tabs = {
        "Receipts": FakeWorksheet(api_sheets.RECEIPT_HEADERS),
        "Cluster Reviews": FakeWorksheet(api_sheets.CLUSTER_REVIEW_HEADERS),
        "CPI": FakeWorksheet(api_sheets.CPI_HEADERS),
    }
    accessors = {"receipts_ws": "Receipts",
                 "cluster_reviews_ws": "Cluster Reviews", "cpi_ws": "CPI"}
    for module in (api_sheets, dashboard_data, api_app):
        for accessor, tab_name in accessors.items():
            if hasattr(module, accessor):
                monkeypatch.setattr(module, accessor,
                                    lambda tab=tabs[tab_name]: tab, raising=True)
    return tabs
