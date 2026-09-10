"""The HTTP surface: C3 persistence, C4 on demand, C6 querying, C1's trail.

The `/api/audit` payloads below are the real shapes n8n holds at the point a
"Persist to Audit API" node would sit — copied from the node code in
`discovery_docs/Expense - High Risk Google Sheets Append.json`, not invented —
because the failure this suite exists to prevent is the API agreeing with itself
while disagreeing with the workflow that calls it.
"""

import json

import pytest

from api import app as app_module


@pytest.fixture
def client(sheet_tabs, fake_cpi):
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


NESTED_PAYLOAD = {
    "audit_engine_input": {
        "expense_id": "1756312345.001",
        "submitted_by": "U04ALEX",
        "receipt": {
            "receipt_id": "1756312345.001",
            "file_name": "ivy-dinner.jpg",
            "merchant": "The Ivy",
            "transaction_date": "2026-08-14",
            "currency": "GBP",
            "subtotal": 240.0,
            "tax": 24.0,
            "total": 264.0,
            "line_items": [{"description": "Set menu x3", "amount": 240.0,
                            "quantity": 3}],
        },
        "policy_checks": {
            "approval": {"cfo_approval_required": False,
                         "line_manager_approval_required": True},
            "flags": [],
            "approvals_required": ["LINE_MANAGER_APPROVAL"],
            "human_review_required": False,
        },
    },
    "contextual_audit": {
        "business_purpose_clear": True,
        "business_relevance": "CLEAR",
        "reasonableness": "REASONABLE",
        "category": "CLIENT_ENTERTAINMENT",
        "risk_factors": [],
        "positive_factors": ["Named client engagement"],
        "recommended_action": "PASS",
        "confidence": 0.91,
        "summary": "Client dinner for three during the Rowan engagement.",
    },
}


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# C3 — every ingested receipt gets a stored verdict
# --------------------------------------------------------------------------- #

def test_audit_persists_a_receipt_with_its_verdict(client, sheet_tabs):
    body = client.post("/api/audit", json=NESTED_PAYLOAD).get_json()

    assert body["receipt_id"] == 1
    # The contextual audit passed it, but £264 measured against a one-head
    # client entertainment guideline does not — so it goes to a human.
    assert body["verdict"] == "high_risk"
    assert body["risk_level"] == "MEDIUM"
    assert body["auto_approved"] is False

    receipts = sheet_tabs["Receipts"].get_all_records()
    assert len(receipts) == 1

    receipt = receipts[0]
    assert receipt["receipt_id"] == "1"
    assert receipt["merchant"] == "The Ivy"
    assert receipt["total_amount"] == "264.0"
    assert receipt["category"] == "client_entertainment"
    assert receipt["submitter"] == "U04ALEX"
    assert receipt["raw_file_reference"] == "ivy-dinner.jpg"
    # 'pending_review', not 'pending' — Review Queue and the dashboard both
    # filter on this exact string.
    assert receipt["status"] == "pending_review"    # high risk waits for Amara
    assert json.loads(receipt["line_items"])[0]["description"] == "Set menu x3"

    assert receipt["verdict"] == "high_risk"
    assert "The Ivy" in receipt["verdict_reason"]
    assert receipt["decided_at"] == ""


def test_receipt_ids_increment_rather_than_colliding(client, sheet_tabs):
    first = client.post("/api/audit", json=NESTED_PAYLOAD).get_json()
    second = client.post("/api/audit", json=NESTED_PAYLOAD).get_json()
    assert (first["receipt_id"], second["receipt_id"]) == (1, 2)
    assert [r["receipt_id"] for r in sheet_tabs["Receipts"].get_all_records()] == [
        "1", "2"]


def test_malformed_ids_already_in_the_sheet_do_not_break_the_next_one(client, sheet_tabs):
    """n8n has written the literal string '=ROW()-1' into receipt_id. Until that
    is fixed upstream, a new insert has to step over it rather than crash."""
    sheet_tabs["Receipts"].append_row(
        ["=ROW()-1", "2026-08-01", "Pret", "[]", "9.20", "0", "subsistence",
         "GBP", "U04SAM", "ref", "pending", "", "", "", "", ""])
    assert client.post(
        "/api/audit", json=NESTED_PAYLOAD).get_json()["receipt_id"] == 1


def test_flat_payload_shape_is_accepted_too(client, sheet_tabs):
    """The shape a "Persist to Audit API" node sends straight after "Final Risk
    Assessment", where n8n has already computed the risk level itself."""
    body = client.post("/api/audit", json={
        "merchant": "Heathrow Express", "transaction_date": "2026-09-01",
        "total": 25.0, "tax": 0.0, "currency": "GBP", "category": "TRAVEL",
        "submitted_by": "U04SAM", "risk_level": "HIGH",
        "summary": "Submitted without a business purpose.",
        "raw_file_reference": "hex.jpg",
    }).get_json()

    assert body["verdict"] == "high_risk"
    receipt = sheet_tabs["Receipts"].get_all_records()[0]
    assert receipt["merchant"] == "Heathrow Express"
    assert "Heathrow Express" in receipt["verdict_reason"]


def test_n8n_supplied_risk_level_is_trusted_over_recomputation(client):
    """n8n has already run the governance prompt; the API must not quietly
    disagree with the verdict the submitter was told in Slack."""
    payload = {**NESTED_PAYLOAD, "final_audit_result": {
        "risk_level": "HIGH", "category": "CLIENT_ENTERTAINMENT",
        "contextual_summary": "Escalated by the workflow.",
        "combined_flags": ["EXTRACTION_REQUIRES_REVIEW"]}}
    body = client.post("/api/audit", json=payload).get_json()
    assert body["verdict"] == "high_risk"
    assert "EXTRACTION_REQUIRES_REVIEW" in body["flags"]


# --------------------------------------------------------------------------- #
# C4 through the API
# --------------------------------------------------------------------------- #

def test_audit_folds_c4_into_the_stored_reason(client, sheet_tabs):
    """A £264 dinner for one is over the re-priced £98.11 guideline, so it goes
    to a human and the stored reason says why in words."""
    body = client.post("/api/audit", json=NESTED_PAYLOAD).get_json()
    validation = body["contextual_validation"]

    assert validation["assessment"] == "OVER_GUIDELINE"
    assert validation["adjusted_limit"] == 98.11
    assert validation["cpi"]["series_id"] == "WLD.FP.CPI.TOTL.ZG"
    # Folded into reasoning, not promoted to a fourth verdict value.
    assert body["verdict"] in {"low_risk", "high_risk"}
    assert "guideline" in sheet_tabs["Receipts"].get_all_records()[
        0]["verdict_reason"]


def test_attendee_count_changes_the_per_head_answer(client):
    payload = {**NESTED_PAYLOAD, "attendee_count": 3}
    validation = client.post(
        "/api/audit", json=payload).get_json()["contextual_validation"]
    assert validation["unit_amount"] == 88.0
    assert validation["assessment"] == "GOOD_DEAL"


def test_validate_endpoint_computes_without_writing_anything(client, sheet_tabs):
    body = client.post("/api/validate", json={
        "total": 88.0, "category": "CLIENT_ENTERTAINMENT"}).get_json()
    assert body["assessment"] == "GOOD_DEAL"
    assert sheet_tabs["Receipts"].get_all_records() == []


def test_auditing_does_not_write_to_the_cpi_sheet(client, sheet_tabs):
    """The CPI tab is reference data refreshed by scripts/sync_cpi.py, not
    something an audit appends to. Writing per request would also add a Sheets
    round-trip to every audit, against Amara's "a few seconds" bar."""
    client.post("/api/audit", json=NESTED_PAYLOAD)
    assert sheet_tabs["CPI"].get_all_records() == []


# --------------------------------------------------------------------------- #
# C6 — filterable, paginated query
# --------------------------------------------------------------------------- #

@pytest.fixture
def populated(sheet_tabs):
    rows = [
        [1, "2026-08-01", "Pret", "[]", 9.20, 0, "subsistence", "GBP", "U04SAM",
         "a.jpg", "approved", "low_risk", "", "", "", ""],
        [2, "2026-08-15", "The Ivy", "[]", 264.00, 24, "client_entertainment",
         "GBP", "U04ALEX", "b.jpg", "approved", "low_risk", "", "", "", ""],
        [3, "2026-09-01", "Trainline", "[]", 88.40, 0, "travel", "GBP", "U04SAM",
         "c.jpg", "pending_review", "high_risk", "", "", "", ""],
        [4, "2026-07-02", "Figma", "[]", 45.00, 0, "software_technology", "GBP",
         "U04ALEX", "d.jpg", "rejected", "high_risk", "", "", "",
         "2026-07-05T09:00:00+00:00"],
    ]
    for row in rows:
        sheet_tabs["Receipts"].append_row(row)
    return sheet_tabs


def test_expenses_defaults_to_approved_only(client, populated):
    body = client.get("/api/expenses").get_json()
    assert body["total"] == 2
    assert {r["merchant"] for r in body["results"]} == {"Pret", "The Ivy"}


def test_expenses_status_all_widens_the_query_for_qa(client, populated):
    assert client.get("/api/expenses?status=all").get_json()["total"] == 4
    assert client.get(
        "/api/expenses?status=pending_review").get_json()["total"] == 1


def test_expenses_filters(client, populated):
    assert client.get(
        "/api/expenses?category=subsistence").get_json()["total"] == 1
    assert client.get(
        "/api/expenses?submitter=U04ALEX").get_json()["total"] == 1
    assert client.get("/api/expenses?min_amount=100").get_json()["total"] == 1
    assert client.get("/api/expenses?max_amount=100").get_json()["total"] == 1
    assert client.get(
        "/api/expenses?start_date=2026-08-10").get_json()["total"] == 1
    assert client.get(
        "/api/expenses?end_date=2026-08-10").get_json()["total"] == 1


def test_expenses_pagination(client, populated):
    first = client.get("/api/expenses?page=1&page_size=1").get_json()
    second = client.get("/api/expenses?page=2&page_size=1").get_json()
    # total is the match count
    assert first["total"] == second["total"] == 2
    assert len(first["results"]) == len(second["results"]) == 1
    assert first["results"][0]["receipt_id"] != second["results"][0]["receipt_id"]
    assert client.get("/api/expenses?page=99").get_json()["results"] == []


def test_expenses_page_size_is_capped_and_floored(client, populated):
    assert client.get(
        "/api/expenses?page_size=500").get_json()["page_size"] == 100
    assert client.get("/api/expenses?page_size=0").get_json()["page_size"] == 1


def test_expenses_dates_come_back_as_iso_strings(client, populated):
    results = client.get("/api/expenses").get_json()["results"]
    assert sorted(r["receipt_date"]
                  for r in results) == ["2026-08-01", "2026-08-15"]


def test_expenses_on_an_empty_sheet_is_an_empty_page_not_an_error(client):
    assert client.get("/api/expenses").get_json() == {
        "total": 0, "page": 1, "page_size": 25, "results": []}


# --------------------------------------------------------------------------- #
# C1 — the paper trail
# --------------------------------------------------------------------------- #

def test_audit_trail_reconstructs_submission_and_verdict(client, sheet_tabs):
    client.post("/api/audit", json=NESTED_PAYLOAD)

    trail = client.get("/api/receipts/1").get_json()
    assert trail["merchant"] == "The Ivy"
    assert trail["verdict"] == "high_risk"


def test_audit_trail_404s_for_an_unknown_receipt(client, sheet_tabs):
    assert client.get("/api/receipts/999").status_code == 404


# --------------------------------------------------------------------------- #
# Auto-approval — what a `low_risk` verdict now does on its own
# --------------------------------------------------------------------------- #

LOW_RISK_PAYLOAD = {
    "merchant": "Trainline", "transaction_date": "2026-09-01", "total": 42.00,
    "tax": 0.0, "currency": "GBP", "category": "TRAVEL", "submitted_by": "U04SAM",
    "risk_level": "LOW", "summary": "Standard class rail fare to a client site.",
}


def test_low_risk_receipt_is_approved_without_a_human(client, sheet_tabs):
    body = client.post("/api/audit", json=LOW_RISK_PAYLOAD).get_json()

    assert body["verdict"] == "low_risk"
    assert body["auto_approved"] is True
    assert body["needs_review"] is False

    # Approved outright, so it lands in the approved-expense reporting straight
    # away rather than sitting in a queue nobody is going to look at.
    receipt = sheet_tabs["Receipts"].get_all_records()[0]
    assert receipt["status"] == "approved"
    assert receipt["decided_at"] == ""


def test_low_risk_receipt_never_reaches_the_review_queue(client, sheet_tabs):
    from dashboard import data
    client.post("/api/audit", json=LOW_RISK_PAYLOAD)
    data.load_receipts.clear()

    df = data.load_expenses()
    assert df["verdict"].tolist() == ["low_risk"]
    assert df[df["verdict"] == "high_risk"].empty


def test_medium_risk_is_not_auto_approved(client, sheet_tabs):
    """The collapse's one real hazard: n8n's MEDIUM tier must not fall into the
    auto-approving bucket."""
    body = client.post("/api/audit", json={**LOW_RISK_PAYLOAD,
                                           "risk_level": "MEDIUM"}).get_json()
    assert body["verdict"] == "high_risk"
    assert body["auto_approved"] is False
    receipt = sheet_tabs["Receipts"].get_all_records()[0]
    assert receipt["status"] == "pending_review"
    assert receipt["decided_at"] == ""
