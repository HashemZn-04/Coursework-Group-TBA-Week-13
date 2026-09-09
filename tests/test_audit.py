"""C4 — inflation-aware contextual validation, and the verdict assembly."""

import pytest

from api import audit
from api.policy import CATEGORY_LIMITS


# --------------------------------------------------------------------------- #
# The acceptance criterion, first and by itself
# --------------------------------------------------------------------------- #

def test_c4_acceptance_criterion_constructed_example(fake_fred):
    """MCP-27: "A receipt priced above a static old limit but within current
    inflation-adjusted benchmark is correctly classified as acceptable (and vice
    versa) — demonstrated with at least one constructed example."

    The example: a £88-per-head client dinner. The handbook says £75 a head
    (Section 5.2, written March 2019 and never uplifted — Addendum B explicitly
    skipped client entertainment). US CPI has risen from 254.277 to 332.813 over
    that period, so £75 in 2019 money is £98.16 today. The dinner is over the
    written figure and comfortably under the re-priced one: the figure is stale,
    the claim is not.
    """
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT")

    assert result["static_limit"] == 75.0
    assert result["adjusted_limit"] == 98.16
    assert result["assessment"] == "GOOD_DEAL"
    assert "Good deal" in result["detail"]

    # And the vice versa: the same claim at £120 a head clears neither figure.
    over = audit.contextual_validation(120.0, "CLIENT_ENTERTAINMENT")
    assert over["assessment"] == "OVER_GUIDELINE"  # 5.2 is a guideline, not a ceiling

    # A hard limit over its adjusted figure is a violation outright. Subsistence
    # is £46/day (£40 uplifted 15% by Addendum B, January 2022), which re-prices
    # to £54.18 — so £60 a day fails on both the old figure and today's.
    violation = audit.contextual_validation(60.0, "SUBSISTENCE")
    assert violation["adjusted_limit"] == 54.18
    assert violation["assessment"] == "POLICY_VIOLATION"


# --------------------------------------------------------------------------- #
# CPI plumbing
# --------------------------------------------------------------------------- #

def test_cpi_for_returns_period_value_and_source(fake_fred):
    assert audit.cpi_for("2019-03-01") == ("2019-03-01", 254.277, "fred")
    assert audit.cpi_for(None) == ("2026-07-01", 332.813, "fred")


def test_cpi_falls_back_to_pinned_snapshot_without_a_key(monkeypatch):
    """No FRED key and no network still has to produce a usable number — but it
    must say so, so a cached figure is never mistaken for a live one."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    audit.cpi_for.cache_clear()
    try:
        date, value, source = audit.cpi_for("2019-03-01")
        assert (date, value, source) == ("2019-03-01", 254.277, "fallback")
        result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT")
        assert result["cpi"]["source"] == "fallback"
        assert result["assessment"] == "GOOD_DEAL"
    finally:
        audit.cpi_for.cache_clear()


def test_fred_missing_observations_are_skipped(fake_fred, monkeypatch):
    """FRED writes a missing month as ".", which float() would choke on."""
    monkeypatch.setattr(audit, "_fred_observations", lambda params: [
        {"date": "2026-06-01", "value": "."},
        {"date": "2026-07-01", "value": "332.813"},
    ])
    audit.cpi_for.cache_clear()
    assert audit.cpi_for(None)[1] == 332.813


def test_quarter_end_rolls_the_year_over():
    assert audit._quarter_end("2019-03-01") == "2019-06-01"
    assert audit._quarter_end("2022-11-01") == "2023-02-01"


def test_inflation_factor_reports_both_endpoints(fake_fred):
    factor, cpi = audit.inflation_factor("2022-01-01")
    assert factor == pytest.approx(332.813 / 282.543)
    assert cpi["base_period"] == "2022-01-01"
    assert cpi["latest_period"] == "2026-07-01"
    assert cpi["source"] == "fred"


# --------------------------------------------------------------------------- #
# Classification bands
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("total,expected", [
    (40.00, "WITHIN_LIMIT"),    # under the written £46
    (46.00, "WITHIN_LIMIT"),    # exactly the written limit
    (46.01, "GOOD_DEAL"),       # a penny over the stale figure
    (54.18, "GOOD_DEAL"),       # exactly the re-priced limit
    (54.19, "POLICY_VIOLATION"),
])
def test_subsistence_bands(fake_fred, total, expected):
    assert audit.contextual_validation(total, "SUBSISTENCE")["assessment"] == expected


def test_uncapped_category_defers_to_approval_thresholds(fake_fred):
    result = audit.contextual_validation(900.0, "TRAVEL")
    assert result["assessment"] == "NO_LIMIT"
    assert result["static_limit"] is None
    assert "no numeric limit" in result["detail"]


def test_per_head_limit_divides_by_attendee_count(fake_fred):
    """A £300 dinner for four is £75 a head — the written limit exactly, not a
    four-times overage."""
    result = audit.contextual_validation(300.0, "CLIENT_ENTERTAINMENT", units=4)
    assert result["unit_amount"] == 75.0
    assert result["assessment"] == "WITHIN_LIMIT"


def test_units_defaults_to_one_when_headcount_is_unknown(fake_fred):
    assert audit.contextual_validation(300.0, "CLIENT_ENTERTAINMENT",
                                       units=None)["units"] == 1


def test_category_is_normalised_before_lookup(fake_fred):
    assert audit.contextual_validation(10, "subsistence")["category"] == "SUBSISTENCE"
    assert audit.contextual_validation(10, "meals")["category"] == "SUBSISTENCE"
    assert audit.contextual_validation(10, None)["category"] == "OTHER"


def test_unreadable_total_is_treated_as_zero_not_a_crash(fake_fred):
    result = audit.contextual_validation("not a number", "SUBSISTENCE")
    assert result["assessment"] == "WITHIN_LIMIT"


def test_every_capped_category_has_a_cpi_base_we_can_resolve(fake_fred):
    for category in CATEGORY_LIMITS:
        result = audit.contextual_validation(1.0, category)
        assert result["cpi"]["source"] == "fred", category
        assert result["adjusted_limit"] > result["static_limit"], category


# --------------------------------------------------------------------------- #
# Verdict assembly (mirrors n8n's "Final Risk Assessment")
# --------------------------------------------------------------------------- #

def test_map_verdict():
    assert audit.map_verdict("HIGH") == "high_risk"
    assert audit.map_verdict("medium") == "flagged"
    assert audit.map_verdict("LOW") == "compliant"
    assert audit.map_verdict("") == "compliant"


CLEAN_AUDIT = {"recommended_action": "PASS", "business_relevance": "CLEAR",
               "reasonableness": "REASONABLE", "confidence": 0.9,
               "risk_factors": []}


def test_clean_receipt_is_compliant():
    verdict, risk, flags = audit.final_verdict({}, CLEAN_AUDIT, None)
    assert (verdict, risk, flags) == ("compliant", "LOW", [])


def test_cfo_threshold_forces_high_risk():
    checks = {"approval": {"cfo_approval_required": True},
              "flags": ["CFO_APPROVAL_THRESHOLD"]}
    verdict, risk, flags = audit.final_verdict(checks, CLEAN_AUDIT, None)
    assert (verdict, risk) == ("high_risk", "HIGH")
    assert flags == ["CFO_APPROVAL_THRESHOLD"]


def test_low_confidence_downgrades_to_flagged():
    verdict, risk, _ = audit.final_verdict({}, {**CLEAN_AUDIT, "confidence": 0.5}, None)
    assert (verdict, risk) == ("flagged", "MEDIUM")


def test_missing_confidence_is_treated_as_zero_like_n8n_does():
    audit_without_confidence = {k: v for k, v in CLEAN_AUDIT.items()
                                if k != "confidence"}
    assert audit.final_verdict({}, audit_without_confidence, None)[0] == "flagged"


def test_c4_violation_escalates_an_otherwise_clean_receipt():
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "POLICY_VIOLATION"})
    assert (verdict, risk) == ("high_risk", "HIGH")
    assert "INFLATION_ADJUSTED_LIMIT_EXCEEDED" in flags


def test_c4_guideline_overage_only_asks_for_an_explanation():
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "OVER_GUIDELINE"})
    assert (verdict, risk) == ("flagged", "MEDIUM")
    assert "OVER_CATEGORY_GUIDELINE" in flags


def test_c4_good_deal_does_not_flag_anything():
    """The whole point of the ticket: an inflation-explained overage is not a
    finding, and must not add a flag."""
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "GOOD_DEAL"})
    assert (verdict, risk, flags) == ("compliant", "LOW", [])


def test_deterministic_and_contextual_flags_merge_without_duplicates():
    checks = {"flags": ["UNCLEAR_RECEIPT_FIELDS", "SHARED"]}
    contextual = {**CLEAN_AUDIT, "risk_factors": ["SHARED", "odd line item"]}
    _, _, flags = audit.final_verdict(checks, contextual, None)
    assert flags == ["UNCLEAR_RECEIPT_FIELDS", "SHARED", "odd line item"]


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #

def test_gbp_claims_carry_no_conversion_caveat(fake_fred):
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT",
                                         currency="GBP")
    assert result["unconverted_currency"] is False
    assert "£88.00 per head" in result["detail"]
    assert "without conversion" not in result["detail"]


def test_foreign_currency_comparison_says_it_is_unconverted(fake_fred):
    """The handbook's limits are GBP and nothing here converts. The comparison
    is still made — the sample data is all USD, so refusing to compare would
    leave every receipt unassessed — but it must not read as if the FX work had
    been done."""
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT",
                                         currency="USD")
    assert result["unconverted_currency"] is True
    assert result["assessment"] == "GOOD_DEAL"       # still classified
    assert "$88.00 per head" in result["detail"]     # claim in its own currency
    assert "£75.00 per head" in result["detail"]     # limit in the handbook's
    assert "without conversion" in result["detail"]
    assert "purchasing power" in result["detail"]
