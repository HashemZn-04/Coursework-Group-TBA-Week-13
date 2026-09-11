"""The Streamlit pages themselves, driven through `streamlit.testing.v1`.

Everything else in this suite tests the layer underneath a page. That left a
whole class of bug uncovered — the Review Queue never emptied after a decision.
So these run each page end to end against the fake worksheets: seed the sheet,
run the script, click the button, assert what a reviewer would actually see.

`AppTest` executes the page in-process, so the `sheet_tabs` fixture's patched
worksheet accessors and the autouse guard against live sheet access both apply
exactly as they do everywhere else.
"""

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import PAGES

HIGH_RISK_RECEIPT = [1, "2026-08-14", "The Ivy", "[]", 264.0, 24.0,
                     "client_entertainment", "GBP", "U04ALEX", "", "b.jpg",
                     "pending_review", "high_risk",
                     "£264.00 at The Ivy is over the per-head guideline.",
                     "2026-08-14T09:00:00+00:00", "", ""]
LOW_RISK_RECEIPT = [2, "2026-08-01", "Pret A Manger", "[]", 9.20, 0.0,
                    "subsistence", "GBP", "U04SAM", "", "a.jpg", "approved",
                    "low_risk", "Auto-approved: within limits.",
                    "2026-08-01T09:00:00+00:00", "", ""]


def run(page: str, **kwargs) -> AppTest:
    app = AppTest.from_file(
        str(PAGES / page), default_timeout=60, **kwargs).run()
    assert not app.exception, app.exception
    return app


def text_of(app: AppTest) -> str:
    """Everything the page rendered as words, so a test can assert on what a
    reviewer reads rather than on a widget index."""
    parts = []
    for block in (app.markdown, app.caption, app.info, app.warning, app.error,
                  app.success, app.subheader, app.title):
        parts.extend(str(element.value) for element in block)
    parts.extend(str(metric.value) for metric in app.metric)
    parts.extend(str(metric.label) for metric in app.metric)
    return "\n".join(parts)


@pytest.fixture
def seeded(sheet_tabs):
    sheet_tabs["Receipts"].append_row(HIGH_RISK_RECEIPT)
    sheet_tabs["Receipts"].append_row(LOW_RISK_RECEIPT)
    return sheet_tabs


# --------------------------------------------------------------------------- #
# E4 — the review queue has to empty
# --------------------------------------------------------------------------- #

def test_a_high_risk_receipt_appears_in_the_queue_with_its_summary(seeded):
    app = run("2_Review_Queue.py")
    assert "The Ivy — £264.00" in text_of(app)
    assert "over the per-head guideline" in text_of(app)
    assert [button.label for button in app.button] == ["Approve", "Reject"]


def test_an_auto_approved_receipt_never_reaches_the_queue(seeded):
    assert "Pret A Manger" not in text_of(run("2_Review_Queue.py"))


def test_a_decided_receipt_leaves_the_queue(seeded):
    """The regression test for E4's second acceptance clause, "queue updates
    without a full manual refresh". The verdict stays `high_risk` for ever —
    Amara's decision does not retract the engine's judgement — so filtering on
    the verdict alone left every decided receipt sitting in the queue, which
    reads as "the button did nothing"."""
    app = run("2_Review_Queue.py")
    app.button[0].click().run()          # Approve

    assert not app.exception
    assert "The Ivy" not in text_of(app)
    assert "No receipts pending review" in text_of(app)

    receipt = seeded["Receipts"].get_all_records()[0]
    assert receipt["status"] == "approved"
    assert receipt["decided_at"]


def test_a_rejection_also_clears_the_queue_and_is_recorded(seeded):
    app = run("2_Review_Queue.py")
    app.button[1].click().run()          # Reject

    assert "The Ivy" not in text_of(app)
    assert seeded["Receipts"].get_all_records()[0]["status"] == "rejected"


def test_an_unassessed_receipt_is_reported_in_red_rather_than_queued(sheet_tabs):
    unassessed = [1, "2026-08-14", "The Ivy", "[]", 264.0, 24.0,
                  "client_entertainment", "GBP", "U04ALEX", "", "b.jpg",
                  "pending_review", "", "", "2026-08-14T09:00:00+00:00", "", ""]
    sheet_tabs["Receipts"].append_row(unassessed)
    app = run("2_Review_Queue.py")

    assert app.error, "an unprocessed receipt must be surfaced as a failure"
    assert "never completed the audit pipeline" in text_of(app)


# --------------------------------------------------------------------------- #
# E2 — at risk and prevented are different numbers
# --------------------------------------------------------------------------- #

def test_spend_overview_separates_money_at_risk_from_money_prevented(seeded):
    app = run("1_Spend_Overview.py")
    metrics = {metric.label: metric.value for metric in app.metric}

    assert metrics["Claimed"] == "£273.20"
    assert metrics["At risk · awaiting your decision"] == "£264.00"
    assert metrics["Leakage prevented"] == "£0.00"
    assert metrics["Approved"] == "£9.20"


def test_rejecting_a_claim_moves_it_from_at_risk_to_prevented(seeded):
    from dashboard import data

    data.update_decision(1, "rejected")
    metrics = {m.label: m.value for m in run("1_Spend_Overview.py").metric}

    assert metrics["At risk · awaiting your decision"] == "£0.00"
    assert metrics["Leakage prevented"] == "£264.00"


def test_totals_carry_the_currency_they_are_counted_in(sheet_tabs):
    """The page used to prefix every total with `$`, including GBP claims."""
    sheet_tabs["Receipts"].append_row(HIGH_RISK_RECEIPT)
    assert "£273" not in "".join(
        m.value for m in run("1_Spend_Overview.py").metric)
    assert any("£264.00" == m.value for m in run("1_Spend_Overview.py").metric)


def test_two_currencies_are_never_added_together_on_the_page(sheet_tabs):
    sheet_tabs["Receipts"].append_row(HIGH_RISK_RECEIPT)
    sheet_tabs["Receipts"].append_row(
        [2, "2026-08-01", "Delta Airlines", "[]", 450.0, 0.0, "travel", "USD",
         "j.chen", "", "", "approved", "low_risk", "Fine",
         "2026-08-01T09:00:00+00:00", "", ""])

    # The summary section shows one currency at a time now, defaulting to
    # GBP — switching its dropdown is how a reviewer sees the other one.
    app = run("1_Spend_Overview.py")
    gbp_values = [metric.value for metric in app.metric]
    assert "£264.00" in gbp_values and "$450.00" not in gbp_values

    app.selectbox(key="currency_summary").select("USD").run()
    usd_values = [metric.value for metric in app.metric]
    assert "$450.00" in usd_values and "£264.00" not in usd_values
    assert not any("714" in value for value in gbp_values + usd_values)


def test_the_currency_dropdown_defaults_to_gbp_when_present(sheet_tabs):
    sheet_tabs["Receipts"].append_row(HIGH_RISK_RECEIPT)
    sheet_tabs["Receipts"].append_row(
        [2, "2026-08-01", "Delta Airlines", "[]", 450.0, 0.0, "travel", "USD",
         "j.chen", "", "", "approved", "low_risk", "Fine",
         "2026-08-01T09:00:00+00:00", "", ""])

    app = run("1_Spend_Overview.py")
    for key in ("currency_summary", "currency_velocity",
                "currency_running_total", "currency_category"):
        assert app.selectbox(key=key).value == "GBP"


def test_each_spend_overview_section_has_its_own_currency_dropdown(sheet_tabs):
    sheet_tabs["Receipts"].append_row(HIGH_RISK_RECEIPT)
    sheet_tabs["Receipts"].append_row(
        [2, "2026-08-01", "Delta Airlines", "[]", 450.0, 0.0, "travel", "USD",
         "j.chen", "", "", "approved", "low_risk", "Fine",
         "2026-08-01T09:00:00+00:00", "", ""])

    app = run("1_Spend_Overview.py")
    for key in ("currency_summary", "currency_velocity",
                "currency_running_total", "currency_category"):
        assert set(app.selectbox(key=key).options) == {"GBP", "USD"}

    # Switching one dropdown leaves the others on their own selection.
    app.selectbox(key="currency_velocity").select("USD").run()
    assert app.selectbox(key="currency_summary").value == "GBP"
    assert app.selectbox(key="currency_velocity").value == "USD"


# --------------------------------------------------------------------------- #
# E3 — policy health
# --------------------------------------------------------------------------- #

def test_policy_health_renders_the_trend_and_the_broken_rules(seeded):
    app = run("4_Policy_Health.py")
    words = text_of(app)

    assert "Policy health over time" in words
    assert "Most-broken rules" in words
    assert app.get(
        "vega_lite_chart"), "the acceptance criterion asks for a chart"


def test_policy_health_does_not_count_an_unassessed_receipt_as_compliant(sheet_tabs):
    """Five assessed receipts cleared, three never assessed. The clearance rate
    is over the assessed five, never over all eight — folding the unassessed
    ones in would read a pipeline outage as a compliance collapse."""
    for index in range(1, 6):
        sheet_tabs["Receipts"].append_row(
            [index, "2026-08-14", "Pret", "[]", 9.20, 0.0, "subsistence", "GBP",
             "U04SAM", "", "a.jpg", "approved", "low_risk", "Fine",
             "2026-08-14T09:00:00+00:00", "", ""])
    for index in range(6, 9):
        sheet_tabs["Receipts"].append_row(
            [index, "2026-08-14", "Pret", "[]", 9.20, 0.0, "subsistence", "GBP",
             "U04SAM", "", "a.jpg", "pending_review", "", "",
             "2026-08-14T09:00:00+00:00", "", ""])

    app = run("4_Policy_Health.py")
    metrics = {metric.label: metric.value for metric in app.metric}

    assert metrics["Assessed"] == "5 of 8"
    assert metrics["Cleared without a human"] == "100%"
    assert app.error, "three unassessed receipts must be flagged, not absorbed"


def test_policy_health_suppresses_a_rate_it_cannot_support(seeded):
    """Two assessed receipts is below the base floor, so the tile shows a dash
    rather than "50%"."""
    metrics = {m.label: m.value for m in run("4_Policy_Health.py").metric}
    assert metrics["Cleared without a human"] == "—"


# --------------------------------------------------------------------------- #
# I2 — patterns of concern
# --------------------------------------------------------------------------- #

@pytest.fixture
def walmart(sheet_tabs):
    """The live sheet's own shape: the same claim, filed repeatedly, by two
    people, spelled three ways."""
    for index, (merchant, submitter) in enumerate(
            [("WAL*MART", "U0B4SSV8YJE"), ("WAL*MART", "U0B4SSV8YJE"),
             ("WAL-MART", "U0B5M5WBV16"), ("Walmart", "U0B5M5WBV16")], start=1):
        sheet_tabs["Receipts"].append_row(
            [index, "08/20/10 13:12:01", merchant, "[]", 5.11, 0.0,
             "subsistence", "USD", submitter, "", "F0C0", "pending_review",
             "", "", "2026-09-09T12:00:00Z", "", ""])
    return sheet_tabs


def test_the_live_duplicate_claims_are_surfaced_for_review(walmart):
    app = run("5_Patterns_of_Concern.py")
    words = text_of(app)

    assert "WAL*MART" in words
    assert "filed the same claim" in words
    assert any(button.label == "Mark reviewed" for button in app.button)


def test_marking_a_pattern_reviewed_records_who_and_when(walmart):
    app = run("5_Patterns_of_Concern.py")
    app.button[0].click().run()

    review = walmart["Cluster Reviews"].get_all_records()[0]
    assert review["pattern"] == "SYNDICATED"
    assert review["receipt_ids"] == "1,2,3,4"
    assert review["reviewed_by"] == "amara.osei"
    assert review["reviewed_at"]
    assert "reviewed" in text_of(app)


def test_a_sheet_with_no_patterns_says_so_rather_than_showing_an_empty_page(seeded):
    app = run("5_Patterns_of_Concern.py")
    assert "No group of claims" in text_of(app)


# --------------------------------------------------------------------------- #
# Every page has to survive an empty sheet
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page", ["1_Spend_Overview.py", "2_Review_Queue.py",
                                  "3_Expense_Browser.py", "4_Policy_Health.py",
                                  "5_Patterns_of_Concern.py"])
def test_every_page_survives_an_empty_sheet(sheet_tabs, page):
    """A fresh deployment has no rows at all. Every page must say so rather
    than raise."""
    app = run(page)
    assert app.info, "an empty sheet should be explained, not silently blank"
