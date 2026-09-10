"""C4 — inflation-aware contextual validation, and the verdict assembly."""

import pytest

from api import audit
from api.policy import CATEGORY_LIMITS


# --------------------------------------------------------------------------- #
# The acceptance criterion, first and by itself
# --------------------------------------------------------------------------- #

def test_c4_acceptance_criterion_constructed_example(fake_cpi):
    """MCP-27: "A receipt priced above a static old limit but within current
    inflation-adjusted benchmark is correctly classified as acceptable (and vice
    versa) — demonstrated with at least one constructed example."

    The example: a £88-per-head client dinner. The handbook says £75 a head
    (Section 5.2, written March 2019 and never uplifted — Addendum B explicitly
    skipped client entertainment). Global consumer prices rose 30.8% between the
    start of 2019 and the end of 2025, so £75 in 2019 money is £98.11 today. The
    dinner is over the written figure and comfortably under the re-priced one:
    the figure is stale, the claim is not.
    """
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT")

    assert result["static_limit"] == 75.0
    assert result["adjusted_limit"] == 98.11
    assert result["assessment"] == "GOOD_DEAL"
    assert "Good deal" in result["detail"]

    # And the vice versa: the same claim at £120 a head clears neither figure.
    over = audit.contextual_validation(120.0, "CLIENT_ENTERTAINMENT")
    # 5.2 is a guideline, not a ceiling
    assert over["assessment"] == "OVER_GUIDELINE"

    # A hard limit over its adjusted figure is a violation outright. Subsistence
    # is £46/day (£40 uplifted 15% by Addendum B, January 2022), which re-prices
    # to £55.83 — so £60 a day fails on both the old figure and today's.
    violation = audit.contextual_validation(60.0, "SUBSISTENCE")
    assert violation["adjusted_limit"] == 55.83
    assert violation["assessment"] == "POLICY_VIOLATION"


# --------------------------------------------------------------------------- #
# CPI plumbing
# --------------------------------------------------------------------------- #

def test_cpi_is_a_single_global_series_not_a_per_country_one(fake_cpi):
    """One world aggregate covers every receipt, wherever it was incurred: what
    is being re-priced is Meridian's own GBP limit, which is the same figure for
    a dinner in Berlin as for one in Bristol."""
    assert audit.CPI_SERIES_ID == "WLD.FP.CPI.TOTL.ZG"


def test_base_period_month_is_ignored_because_the_series_is_annual(fake_cpi):
    """A real precision loss worth pinning: the global series is published once
    a year, so March and November 2019 re-price from the same point."""
    assert audit.cpi_for("2019-03-01") == audit.cpi_for("2019-11-01")
    assert audit.cpi_for("2019-03-01")[0] == "2019"


def test_latest_is_labelled_with_the_last_year_actually_published(fake_cpi):
    """The vintage must never claim a year we do not have. The rates end at
    2025, so the reported latest period is 2025 — even though the compounded
    level it carries is the level reached at the *end* of 2025."""
    year, _, source = audit.cpi_for(None)
    assert (year, source) == ("2025", "worldbank")


def test_inflation_factor_compounds_the_annual_rates(fake_cpi):
    """2019 is measured from the start of the year — the handbook was issued
    that March, so nearly all of 2019's own inflation applies to it."""
    from tests.conftest import GLOBAL_RATES
    expected = 1.0
    for year in range(2019, 2026):
        expected *= 1 + GLOBAL_RATES[year] / 100
    factor, cpi = audit.inflation_factor("2019-03-01")
    assert factor == pytest.approx(expected, rel=1e-6)
    assert (cpi["base_period"], cpi["latest_period"]) == ("2019", "2025")
    assert cpi["source"] == "worldbank"


def test_cpi_falls_back_to_the_pinned_snapshot_when_offline(monkeypatch):
    """No network still has to produce a usable number — and say that it did,
    so a cached figure is never mistaken for a live one. No API key is involved
    either way; the World Bank needs none."""
    def boom(*_a, **_k):
        raise audit.requests.RequestException("offline")

    monkeypatch.setattr(audit.requests, "get", boom)
    audit.global_inflation_rates.cache_clear()
    audit.cpi_for.cache_clear()
    try:
        rates, source = audit.global_inflation_rates()
        assert source == "fallback" and rates == audit.GLOBAL_INFLATION_FALLBACK
        result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT")
        assert result["cpi"]["source"] == "fallback"
        assert result["assessment"] == "GOOD_DEAL"
    finally:
        audit.global_inflation_rates.cache_clear()
        audit.cpi_for.cache_clear()


def test_a_base_year_outside_the_series_is_clamped_not_a_crash(fake_cpi):
    assert audit.cpi_for("1990-01-01")[0] == "2015"
    assert audit.cpi_for("2099-01-01")[0] == "2025"


# --------------------------------------------------------------------------- #
# Classification bands
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("total,expected", [
    (40.00, "WITHIN_LIMIT"),    # under the written £46
    (46.00, "WITHIN_LIMIT"),    # exactly the written limit
    (46.01, "GOOD_DEAL"),       # a penny over the stale figure
    (55.83, "GOOD_DEAL"),       # exactly the re-priced limit
    (55.84, "POLICY_VIOLATION"),
])
def test_subsistence_bands(fake_cpi, total, expected):
    assert audit.contextual_validation(total, "SUBSISTENCE")[
        "assessment"] == expected


def test_uncapped_category_defers_to_approval_thresholds(fake_cpi):
    result = audit.contextual_validation(900.0, "TRAVEL")
    assert result["assessment"] == "NO_LIMIT"
    assert result["static_limit"] is None
    assert "no numeric limit" in result["detail"]


def test_per_head_limit_divides_by_attendee_count(fake_cpi):
    """A £300 dinner for four is £75 a head — the written limit exactly, not a
    four-times overage."""
    result = audit.contextual_validation(
        300.0, "CLIENT_ENTERTAINMENT", units=4)
    assert result["unit_amount"] == 75.0
    assert result["assessment"] == "WITHIN_LIMIT"


def test_units_defaults_to_one_when_headcount_is_unknown(fake_cpi):
    assert audit.contextual_validation(300.0, "CLIENT_ENTERTAINMENT",
                                       units=None)["units"] == 1


def test_category_is_normalised_before_lookup(fake_cpi):
    assert audit.contextual_validation(10, "subsistence")[
        "category"] == "SUBSISTENCE"
    assert audit.contextual_validation(
        10, "meals")["category"] == "SUBSISTENCE"
    assert audit.contextual_validation(10, None)["category"] == "OTHER"


def test_unreadable_total_is_treated_as_zero_not_a_crash(fake_cpi):
    result = audit.contextual_validation("not a number", "SUBSISTENCE")
    assert result["assessment"] == "WITHIN_LIMIT"


def test_every_capped_category_has_a_cpi_base_we_can_resolve(fake_cpi):
    for category in CATEGORY_LIMITS:
        result = audit.contextual_validation(1.0, category)
        assert result["cpi"]["source"] == "worldbank", category
        assert result["adjusted_limit"] > result["static_limit"], category


# --------------------------------------------------------------------------- #
# Verdict assembly (mirrors n8n's "Final Risk Assessment")
# --------------------------------------------------------------------------- #

def test_map_verdict():
    assert audit.map_verdict("HIGH") == "high_risk"
    assert audit.map_verdict("LOW") == "low_risk"


def test_medium_risk_goes_to_review_not_auto_approval():
    """n8n still emits MEDIUM ("needs an employee explanation") to pick its
    Slack reply, but we store two verdicts. MEDIUM must fold up, not down:
    `low_risk` now auto-approves, and auto-approving something the engine was
    unsure about is the one failure this collapse could have introduced."""
    assert audit.map_verdict("medium") == "high_risk"


def test_unknown_risk_level_defaults_to_review():
    """Same reasoning — an unrecognised value must not fall through to an
    automatic approval."""
    assert audit.map_verdict("") == "high_risk"
    assert audit.map_verdict("something new") == "high_risk"


CLEAN_AUDIT = {"recommended_action": "PASS", "business_relevance": "CLEAR",
               "reasonableness": "REASONABLE", "confidence": 0.9,
               "risk_factors": []}


def test_clean_receipt_is_low_risk():
    verdict, risk, flags = audit.final_verdict({}, CLEAN_AUDIT, None)
    assert (verdict, risk, flags) == ("low_risk", "LOW", [])


def test_cfo_threshold_forces_high_risk():
    checks = {"approval": {"cfo_approval_required": True},
              "flags": ["CFO_APPROVAL_THRESHOLD"]}
    verdict, risk, flags = audit.final_verdict(checks, CLEAN_AUDIT, None)
    assert (verdict, risk) == ("high_risk", "HIGH")
    assert flags == ["CFO_APPROVAL_THRESHOLD"]


def test_low_confidence_sends_it_to_review():
    """Low confidence used to mean "flagged". With no middle tier it must reach
    a human rather than be auto-approved."""
    verdict, risk, _ = audit.final_verdict(
        {}, {**CLEAN_AUDIT, "confidence": 0.5}, None)
    assert (verdict, risk) == ("high_risk", "MEDIUM")


def test_missing_confidence_is_treated_as_zero_like_n8n_does():
    audit_without_confidence = {k: v for k, v in CLEAN_AUDIT.items()
                                if k != "confidence"}
    assert audit.final_verdict({}, audit_without_confidence, None)[
        0] == "high_risk"


def test_c4_violation_escalates_an_otherwise_clean_receipt():
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "POLICY_VIOLATION"})
    assert (verdict, risk) == ("high_risk", "HIGH")
    assert "INFLATION_ADJUSTED_LIMIT_EXCEEDED" in flags


def test_c4_guideline_overage_reaches_a_human():
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "OVER_GUIDELINE"})
    assert (verdict, risk) == ("high_risk", "MEDIUM")
    assert "OVER_CATEGORY_GUIDELINE" in flags


def test_c4_good_deal_does_not_flag_anything():
    """The whole point of the ticket: an inflation-explained overage is not a
    finding, and must not add a flag."""
    verdict, risk, flags = audit.final_verdict(
        {}, CLEAN_AUDIT, {"assessment": "GOOD_DEAL"})
    assert (verdict, risk, flags) == ("low_risk", "LOW", [])


def test_deterministic_and_contextual_flags_merge_without_duplicates():
    checks = {"flags": ["UNCLEAR_RECEIPT_FIELDS", "SHARED"]}
    contextual = {**CLEAN_AUDIT, "risk_factors": ["SHARED", "odd line item"]}
    _, _, flags = audit.final_verdict(checks, contextual, None)
    assert flags == ["UNCLEAR_RECEIPT_FIELDS", "SHARED", "odd line item"]


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #

def test_gbp_claims_carry_no_conversion_caveat(fake_cpi):
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT",
                                         currency="GBP")
    assert result["unconverted_currency"] is False
    assert "£88.00 per head" in result["detail"]
    assert "without conversion" not in result["detail"]


def test_foreign_currency_comparison_says_it_is_unconverted(fake_cpi):
    """The handbook's limits are GBP and nothing here converts. The comparison
    is still made — the sample data is all USD, so refusing to compare would
    leave every receipt unassessed — but it must not read as if the FX work had
    been done."""
    result = audit.contextual_validation(88.0, "CLIENT_ENTERTAINMENT",
                                         currency="USD")
    assert result["unconverted_currency"] is True
    assert result["assessment"] == "GOOD_DEAL"       # still classified
    # claim in its own currency
    assert "$88.00 per head" in result["detail"]
    assert "£75.00 per head" in result["detail"]     # limit in the handbook's
    assert "without conversion" in result["detail"]
    assert "purchasing power" in result["detail"]


# --------------------------------------------------------------------------- #
# The pipeline's terminal-state invariant
# --------------------------------------------------------------------------- #

def test_every_receipt_terminates_in_exactly_one_of_two_outcomes(fake_cpi):
    """Deterministic checks -> CPI validation -> final risk assessment, and the
    split is always low (auto-approved) or high_risk (queued). There is no third
    outcome, and no combination of inputs may produce one — a receipt that is
    neither auto-approved nor queued would sit in the system untouched by
    anything.
    """
    from itertools import product
    from api.policy import VERDICTS

    actions = [None, "PASS", "NEEDS_EMPLOYEE_EXPLANATION", "NEEDS_HUMAN_REVIEW"]
    relevances = [None, "CLEAR", "PLAUSIBLE", "UNCLEAR", "LIKELY_PERSONAL"]
    reasonableness = [None, "REASONABLE", "QUESTIONABLE", "UNREASONABLE",
                      "INSUFFICIENT_INFORMATION"]
    assessments = [None, "WITHIN_LIMIT", "GOOD_DEAL", "OVER_GUIDELINE",
                   "POLICY_VIOLATION", "NO_LIMIT"]
    checks = [{}, {"human_review_required": True},
              {"approval": {"cfo_approval_required": True}},
              {"flags": ["EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF"]}]

    for action, relevance, reason, assessment, policy in product(
            actions, relevances, reasonableness, assessments, checks):
        contextual = {"recommended_action": action, "confidence": 0.9,
                      "business_relevance": relevance, "reasonableness": reason}
        verdict, risk, _ = audit.final_verdict(
            policy, contextual, {"assessment": assessment} if assessment else None)
        assert verdict in VERDICTS, (verdict, contextual, policy, assessment)
        assert risk in {"LOW", "MEDIUM", "HIGH"}
        # low_risk is the auto-approving outcome, so it may only be reached
        # with no concern raised anywhere.
        if verdict == "low_risk":
            assert risk == "LOW"


def test_no_risk_level_maps_to_an_absent_verdict(fake_cpi):
    """Whatever n8n sends, map_verdict resolves to a real terminal state — it
    never returns None or an unrecognised string that would leave a receipt in
    neither bucket."""
    from api.policy import VERDICTS
    for level in ["HIGH", "MEDIUM", "LOW", "", None, "UNKNOWN", "low", 0]:
        assert audit.map_verdict(level) in VERDICTS
