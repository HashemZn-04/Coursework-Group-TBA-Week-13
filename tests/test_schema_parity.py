"""C1 — the schema is written down in more than one place, so pin them together.

Three components read and write these tabs: the Flask API (`api/sheets.py`), the
Streamlit dashboard (`dashboard/data.py`), and n8n's Google Sheets node (whose
column mapping lives in the exported workflow JSON). A column added to one and
not the others produces silently misaligned rows rather than an error, so this
compares all three against each other.
"""

import json
from pathlib import Path

import pytest

from api import sheets as api_sheets
from dashboard import data as dashboard_data

WORKFLOW = (Path(__file__).resolve().parents[1] / "discovery_docs" /
            "Expense - High Risk Google Sheets Append.json")


@pytest.mark.parametrize("name", ["RECEIPT_HEADERS", "VERDICT_HEADERS",
                                  "DECISION_HEADERS"])
def test_api_and_dashboard_agree_on_the_columns(name):
    assert getattr(api_sheets, name) == getattr(dashboard_data, name)


def test_receipt_columns_cover_the_agreed_b3_schema():
    """Every field B3 locked, mapped onto its column name here. `source_channel`
    and `payment_method` were dropped when the sheet replaced Postgres — Mason
    asked what payment_method was even sourced from and there was no answer."""
    required = {"receipt_id", "receipt_date", "merchant", "line_items", "tax",
                "total_amount", "currency", "submitter", "raw_file_reference",
                "status", "created_at"}
    assert required <= set(api_sheets.RECEIPT_HEADERS)


def test_the_audit_trail_can_be_reconstructed_from_the_three_tabs():
    """C1's acceptance criterion, as columns: what was submitted, what the AI
    decided and why, and what the human did about it."""
    assert {"receipt_id", "status"} <= set(api_sheets.RECEIPT_HEADERS)
    assert {"receipt_id", "verdict", "reason", "created_at"} <= set(
        api_sheets.VERDICT_HEADERS)
    assert {"receipt_id", "decision", "decided_by", "decided_at"} <= set(
        api_sheets.DECISION_HEADERS)


@pytest.mark.skipif(not WORKFLOW.exists(),
                    reason="workflow export not present in this checkout")
def test_n8n_sheets_node_writes_the_same_receipt_columns():
    """If AA re-exports the workflow with a different column mapping, this is
    what catches it before a demo does."""
    nodes = json.loads(WORKFLOW.read_text())["nodes"]
    sheets_nodes = [n for n in nodes
                    if n.get("type") == "n8n-nodes-base.googleSheets"]
    assert sheets_nodes, "no Google Sheets node in the exported workflow"

    for node in sheets_nodes:
        mapped = list(node["parameters"]["columns"]["value"])
        assert mapped == api_sheets.RECEIPT_HEADERS, node.get("name")
