"""C5 — the natural-language summary Amara makes a one-click call from.

The acceptance criterion names four things the summary must contain: what was
flagged, why, the amount, and the submitter. Each of those is asserted directly
below rather than checked by eye.
"""

from api.summary import build_summary, describe_flags, format_money

RECEIPT = {
    "merchant": "The Ivy",
    "transaction_date": "2026-08-14",
    "total": 264.00,
    "currency": "GBP",
    "category": "CLIENT_ENTERTAINMENT",
}


def test_c5_acceptance_criterion_summary_contains_what_why_amount_and_who():
    result = build_summary(
        RECEIPT, "high_risk",
        flags=["CFO_APPROVAL_THRESHOLD", "EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"],
        contextual_summary="Client dinner for three, business purpose stated in "
                           "the submitter's message.",
        validation={"assessment": "GOOD_DEAL",
                    "detail": "Good deal: 88.00 per head is over the handbook's "
                              "75.00 per head but within 98.16 per head."},
        submitter="U04ALEX")
    summary = result["summary"]

    assert "£264.00" in summary                      # amount
    assert "U04ALEX" in summary                      # submitter
    assert "The Ivy" in summary                      # what
    assert "Needs your decision" in summary          # the ask
    assert "CFO approval threshold" in summary       # why (deterministic)
    assert "more than a month after" in summary      # why (deterministic)
    # why (the LLM's reasoning)
    assert "Client dinner for three" in summary
    assert "Good deal" in summary                    # why (C4)


def test_slack_and_dashboard_renderings_carry_the_same_facts():
    """Amara reads one of these in Slack and the other in the dashboard. They
    must not be able to disagree."""
    result = build_summary(RECEIPT, "high_risk", flags=["RECEIPT_MISSING"],
                           contextual_summary="No receipt image attached.",
                           submitter="U04ALEX")
    for fact in ("£264.00", "The Ivy", "U04ALEX", "No receipt image attached."):
        assert fact in result["summary"]
        assert fact in result["slack_message"]
    assert result["slack_message"].startswith("*Needs your decision*")


def test_low_risk_receipt_says_it_was_approved_not_merely_unremarkable():
    """`low_risk` now carries an automatic approval, so the wording has to say
    that happened — "no action needed" would understate what the system just
    did."""
    result = build_summary(RECEIPT, "low_risk", flags=[], submitter="U04ALEX")
    assert result["headline"] == "Auto-approved"
    assert "approved automatically" in result["summary"]
    assert "No human review was required" in result["summary"]


def test_llm_risk_factors_pass_through_verbatim():
    """Deterministic codes get translated; free-text risk factors from the
    governance prompt are already English and must not be mangled."""
    reasons = describe_flags(["RECEIPT_MISSING", "Line items look like one "
                              "purchase split across two claims"])
    assert reasons == [
        "no receipt image was attached to the claim",
        "Line items look like one purchase split across two claims",
    ]


def test_duplicate_and_empty_flags_are_dropped():
    assert describe_flags(["RECEIPT_MISSING", "RECEIPT_MISSING", "", None]) == [
        "no receipt image was attached to the claim"]


def test_no_limit_validation_detail_is_not_padded_into_the_reasons():
    """"The handbook sets no numeric limit for travel" is true but says nothing
    a reviewer needs, so it stays out of the summary."""
    result = build_summary({**RECEIPT, "category": "TRAVEL"}, "high_risk",
                           flags=["UNCLEAR_RECEIPT_FIELDS"],
                           validation={"assessment": "NO_LIMIT",
                                       "detail": "The handbook sets no numeric limit"})
    assert "no numeric limit" not in result["summary"]


def test_missing_fields_degrade_to_readable_text():
    result = build_summary({}, "high_risk", flags=[])
    assert "Unknown merchant" in result["summary"]
    assert "unknown submitter" in result["summary"]
    assert "date not read" in result["summary"]


def test_format_money():
    assert format_money(1234.5, "GBP") == "£1,234.50"
    assert format_money(1234.5, "USD") == "$1,234.50"
    assert format_money("12.3", "EUR") == "€12.30"
    assert format_money(10, "SEK") == "10.00 SEK"        # no symbol we know
    assert format_money(None, "GBP") == "£0.00"
    assert format_money("not a number", None) == "0.00"
