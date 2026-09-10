"""C1 — the schema is written down in more than one place, so pin them together.

Two components read and write the Receipts tab: the Flask API
(`api/sheets.py`) and the Streamlit dashboard (`dashboard/data.py`). A column
added to one and not the other produces silently misaligned rows rather than
an error, so this compares them against each other.
"""

import json
from pathlib import Path

import pytest

from api import sheets as api_sheets
from dashboard import data as dashboard_data

WORKFLOW = (Path(__file__).resolve().parents[1] / "discovery_docs" /
            "Expense - High Risk Google Sheets Append.json")


@pytest.mark.parametrize("name", ["RECEIPT_HEADERS", "CLUSTER_REVIEW_HEADERS"])
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


def test_the_audit_trail_can_be_reconstructed_from_one_row():
    """C1's acceptance criterion, as columns: what was submitted, what the AI
    decided and why, and what the human did about it — all on the same row now
    that there is one Receipts tab."""
    assert {"receipt_id", "status", "verdict", "verdict_reason",
            "decided_at"} <= set(api_sheets.RECEIPT_HEADERS)


@pytest.mark.skip(
    reason="the n8n workflow still targets the old multi-tab schema; re-enable "
           "once the AA's export is updated to the single-table Receipts model")
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
