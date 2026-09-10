"""
C4 — Contextual Validation, inflation-aware (MCP-27), plus the verdict mapping
C3/C5 share.

Where this sits in the pipeline. Every receipt runs the same three stages, in
this order, and comes out one of exactly two ways:

    1. Deterministic policy checks   hard limits, approval thresholds, the
                                     one-month cutoff (n8n's "Deterministic
                                     Policy Checks" node)
    2. Contextual validation (C4)    the receipt against its category limit,
                                     re-priced to today's CPI — this module
    3. Final risk assessment         combine both with the governance prompt's
                                     contextual read, and split:

           low_risk   -> approved automatically, nobody looks at it
           high_risk  -> the CFO's review queue

There is no third outcome and no "assessed but parked" state. A receipt holding
neither verdict has not been through the pipeline at all — that is a failure to
process it, not a classification, and the dashboard reports it as one.

The problem this solves is the brief's "Policy Decay": Amara's handbook was
written in 2019 and its numbers have not moved since, so a receipt can be over
the written limit while being an entirely normal 2026 price. Comparing against
the static figure alone produces false flags; comparing against nothing produces
no control at all. So every limit in `api.policy` carries the period it was set
in, and this module re-prices it to today's CPI before comparing:

    adjusted_limit = static_limit * (CPI_now / CPI_at_the_time_the_limit_was_set)

and then classifies the receipt into one of:

    WITHIN_LIMIT      total is inside the original figure — no argument either way
    GOOD_DEAL         over the stale figure, inside the re-priced one — this is
                      the case the brief cares about, and it is *not* a flag
    OVER_GUIDELINE    over the re-priced figure, but the handbook calls that
                      figure a guideline (5.2) rather than a ceiling
    POLICY_VIOLATION  over the re-priced figure on a hard limit
    NO_LIMIT          the handbook sets no numeric ceiling for this category

The LLM half of the audit (contextual reasonableness) runs in n8n's "AI
Contextual Audit" node against `api.governance_prompt.SYSTEM_PROMPT`, using the
team's existing OpenAI credential there. This module deliberately holds no LLM
call: it is the deterministic, testable, reproducible half, and it produces the
same answer for the same receipt every time — which is what makes it auditable.

Inflation comes from one global series — the World Bank's world aggregate for
annual consumer-price inflation — rather than a per-country index. Meridian's
limits are a single firm-wide set of figures, so re-pricing them needs exactly
one inflation number; and a receipt from Berlin, Boston or Bristol is measured
against the same firm limit either way. One source, no per-country routing, and
no API key.

The honest cost of that choice: the global series is **annual and published in
arrears** (latest is 2025, where a national index like the UK's runs monthly to
2026-07). So the adjustment is a year-granular figure that lags the present by
roughly a year, and it always under-states rather than over-states the
re-pricing. Every result carries the years it actually used, so this is visible
rather than assumed.
"""

import os
from functools import lru_cache

import requests
from dotenv import load_dotenv

try:  # importable both as `api.audit` and as a sibling of `app.py`
    from api.policy import (APPROVAL_THRESHOLDS, REPORTING_CURRENCY,
                            VERDICT_HIGH, VERDICT_LOW, Limit, limit_for,
                            normalise_category)
    from api.summary import format_money
except ImportError:  # pragma: no cover - exercised only by `python api/app.py`
    from policy import (APPROVAL_THRESHOLDS, REPORTING_CURRENCY, VERDICT_HIGH,
                        VERDICT_LOW, Limit, limit_for, normalise_category)
    from summary import format_money

load_dotenv()

#: n8n still computes three risk levels, because it uses them to pick between
#: three different Slack replies. We store two verdicts. MEDIUM — the workflow's
#: "needs an explanation from the employee" tier — maps to `high_risk`: it is by
#: definition not something the engine is confident enough to auto-approve.
RISK_TO_VERDICT = {"HIGH": VERDICT_HIGH, "MEDIUM": VERDICT_HIGH,
                   "LOW": VERDICT_LOW}


def map_verdict(risk_level: str) -> str:
    """n8n's risk level -> the verdict vocabulary stored on the Receipts row.

    An unrecognised risk level resolves to `high_risk`, not `low_risk`. `low_risk`
    now carries an automatic approval, so the safe direction for an unknown
    value is towards a human, not past one.
    """
    return RISK_TO_VERDICT.get(str(risk_level).strip().upper(), VERDICT_HIGH)


# --------------------------------------------------------------------------- #
# Global inflation (stands in for C2's scheduled pull until AA builds it)
# --------------------------------------------------------------------------- #

#: World Bank: world aggregate, "Inflation, consumer prices (annual %)".
#: Free, no key, no signup.
WORLD_BANK_URL = ("https://api.worldbank.org/v2/country/WLD/"
                  "indicator/FP.CPI.TOTL.ZG")
WORLD_BANK_TIMEOUT = 15
CPI_SERIES_ID = "WLD.FP.CPI.TOTL.ZG"

#: Published global annual inflation, %, captured from the World Bank
#: 2026-09-09. Used when the API cannot be reached so a demo still produces a
#: defensible number; every result says which source it came from.
#: Full published precision, not rounded — a 2dp copy drifts about a penny per
#: £100 of limit against the live figures, which would make the offline demo and
#: the live one disagree for no reason anyone could explain.
GLOBAL_INFLATION_FALLBACK: dict[int, float] = {
    2015: 1.43702380935655, 2016: 1.59691227583204, 2017: 2.22314331448899,
    2018: 2.44258329692817, 2019: 2.20607305781525, 2020: 1.90509722047501,
    2021: 3.47540320289875, 2022: 8.08169507021982, 2023: 5.79944107391962,
    2024: 3.01447576977999, 2025: 3.0414132155654,
}


@lru_cache(maxsize=1)
def global_inflation_rates() -> tuple[dict[int, float], str]:
    """``({year: annual inflation %}, source)`` for the world aggregate.

    Cached for the life of the process — the series only gains a value once a
    year, and C2's scheduled pull will eventually front this.
    """
    try:
        response = requests.get(
            WORLD_BANK_URL, params={"format": "json", "per_page": 200},
            timeout=WORLD_BANK_TIMEOUT)
        response.raise_for_status()
        rows = response.json()[1]
        rates = {int(row["date"]): float(row["value"])
                 for row in rows if row.get("value") is not None}
        if not rates:
            raise ValueError("world aggregate returned no observations")
        return rates, "worldbank"
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return dict(GLOBAL_INFLATION_FALLBACK), "fallback"


def _price_index(rates: dict[int, float]) -> tuple[dict[int, float], float]:
    """Chain annual rates into price levels, anchored at 100.

    The World Bank publishes a rate per year for the world aggregate, not an
    index, so the levels we compare are compounded from those rates. Returns the
    level at the *start* of each year, plus the level reached at the *end* of the
    last published year.

    Start-of-year for the base is the deliberate choice: the handbook was issued
    in March 2019, so nearly all of 2019's own inflation applies to it. Measuring
    from the end of 2019 would silently drop a year of it.
    """
    index, level = {}, 100.0
    for year in sorted(rates):
        index[year] = level
        level *= 1 + rates[year] / 100
    return index, level


def _year_of(period: str | int) -> int:
    return int(str(period)[:4])


@lru_cache(maxsize=32)
def cpi_for(period: str | int | None = None) -> tuple[str, float, str]:
    """Price level for a year, as ``(year, index_level, source)``.

    `period` is anything starting with a year (``"2019-03-01"`` or ``2019``),
    giving the level at the start of that year. None gives the level at the end
    of the latest published year — labelled with that year, so the reported
    vintage is the last year we actually have data for and never a year we do
    not.

    Because the global series is annual, the month in a base period is ignored:
    a limit set in March 2019 and one set in November 2019 re-price identically.
    """
    rates, source = global_inflation_rates()
    index, end_level = _price_index(rates)
    last_year = max(rates)
    if period is None:
        return str(last_year), round(end_level, 4), source
    year = min(max(_year_of(period), min(index)), last_year)  # clamp to series
    return str(year), round(index[year], 4), source


def latest_cpi() -> float:
    """Most recent global price level on the chained index."""
    return cpi_for(None)[1]


def inflation_factor(base_period: str) -> tuple[float, dict]:
    """How much global prices have moved since `base_period`, plus provenance."""
    base_year, base_value, base_source = cpi_for(base_period)
    latest_year, latest_value, latest_source = cpi_for(None)
    provenance = {
        "series_id": CPI_SERIES_ID,
        "base_period": base_year,
        "base_value": base_value,
        "latest_period": latest_year,
        "latest_value": latest_value,
        "source": ("worldbank" if base_source == latest_source == "worldbank"
                   else "fallback"),
    }
    return latest_value / base_value, provenance


def inflation_adjusted_limit(static_limit: float, base_period: str) -> float:
    """A limit set in `base_period`, restated in today's money."""
    factor, _ = inflation_factor(base_period)
    return round(static_limit * factor, 2)


# --------------------------------------------------------------------------- #
# C4 proper
# --------------------------------------------------------------------------- #

def contextual_validation(total: float, category: str, units: int = 1,
                          currency: str | None = None) -> dict:
    """Classify a receipt against its inflation-adjusted handbook limit.

    `units` is the divisor the limit's basis calls for — attendee count for a
    per-head limit, days claimed for a per-day one. It defaults to 1, which is
    the right answer for a single claim and a safe (strictest) reading when the
    receipt does not tell us the headcount. Attendee count is one of the fields
    QA flagged as missing from the schema; until it is captured, a two-person
    client dinner is measured against the one-person limit, so a per-head
    overage here means "ask", not "reject".

    `currency` does not convert anything — no FX source is wired in. The
    handbook's limits are GBP and Section 12.2 wants conversion at the rate on
    the transaction date, which nothing in this pipeline does yet. Rather than
    pretend, a non-GBP receipt is still compared against the limit and the
    result says out loud that the comparison is unconverted, so a reviewer reads
    it knowing that. Amara was explicit that exchange rate and local purchasing
    power both matter here, so this is a gap to close, not a detail.
    """
    category = normalise_category(category)
    amount = _to_float(total)
    limit = limit_for(category)

    if limit is None:
        return {
            "category": category,
            "assessment": "NO_LIMIT",
            "static_limit": None,
            "adjusted_limit": None,
            "detail": (
                f"The handbook sets no numeric limit for {_label(category)}; "
                f"this claim is governed by the general approval thresholds "
                f"(line manager over "
                f"{APPROVAL_THRESHOLDS['line_manager']:,.0f}, CFO over "
                f"{APPROVAL_THRESHOLDS['cfo']:,.0f})."
            ),
        }

    units = max(int(units or 1), 1)
    unit_amount = round(amount / units, 2)
    factor, cpi = inflation_factor(limit.base_period)
    adjusted = round(limit.amount * factor, 2)
    # Guard the pathological case of a deflating index, where the re-priced
    # figure would otherwise be *stricter* than the written one.
    ceiling = max(adjusted, limit.amount)

    if unit_amount <= limit.amount:
        assessment = "WITHIN_LIMIT"
    elif unit_amount <= ceiling:
        assessment = "GOOD_DEAL"
    else:
        assessment = "POLICY_VIOLATION" if limit.hard else "OVER_GUIDELINE"

    unconverted = bool(currency) and str(
        currency).upper() != REPORTING_CURRENCY
    return {
        "category": category,
        "assessment": assessment,
        "basis": limit.basis,
        "units": units,
        "unit_amount": unit_amount,
        "static_limit": limit.amount,
        "adjusted_limit": adjusted,
        "inflation_factor": round(factor, 4),
        "hard_limit": limit.hard,
        "source": limit.source,
        "currency": (currency or REPORTING_CURRENCY).upper(),
        "unconverted_currency": unconverted,
        "cpi": cpi,
        "detail": _validation_detail(assessment, limit, unit_amount, adjusted,
                                     factor, currency, unconverted),
    }


def _validation_detail(assessment: str, limit: Limit, unit_amount: float,
                       adjusted: float, factor: float,
                       currency: str | None = None,
                       unconverted: bool = False) -> str:
    per = {"per_head": " per head", "per_day": " per day",
           "per_month": " per month"}.get(limit.basis, "")
    claimed = f"{format_money(unit_amount, currency or REPORTING_CURRENCY)}{per}"
    written = f"{format_money(limit.amount, REPORTING_CURRENCY)}{per}"
    repriced = f"{format_money(adjusted, REPORTING_CURRENCY)}{per}"
    since = limit.base_period[:7]
    inflation = f"prices are up {(factor - 1) * 100:.1f}% since {since}"

    if assessment == "WITHIN_LIMIT":
        detail = (f"{claimed} is within the handbook limit of {written} "
                  f"({limit.source}).")
    elif assessment == "GOOD_DEAL":
        detail = (f"Good deal: {claimed} is over the handbook's {written} but "
                  f"within {repriced}, the same limit restated in today's money "
                  f"({inflation}). The written figure is stale, not the claim.")
    elif assessment == "OVER_GUIDELINE":
        detail = (f"{claimed} is over {repriced} — the handbook's {written} "
                  f"restated in today's money ({inflation}). {limit.source} "
                  f"treats this figure as a guideline rather than a ceiling, so "
                  f"this is a question for the approver, not an automatic breach.")
    else:
        detail = (f"Policy violation: {claimed} exceeds {repriced} — the "
                  f"handbook's {written} restated in today's money ({inflation}). "
                  f"Over the limit on both the old figure and the current one.")

    if unconverted:
        detail += (f" Compared without conversion: the claim is in "
                   f"{str(currency).upper()} and the limit is in "
                   f"{REPORTING_CURRENCY}, so weigh the exchange rate and local "
                   f"purchasing power before acting on this comparison.")
    return detail


def _label(category: str) -> str:
    return category.replace("_", " ").lower()


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# Risk assembly — mirrors n8n's "Final Risk Assessment" node
# --------------------------------------------------------------------------- #

def final_verdict(policy_checks: dict, contextual_audit: dict,
                  validation: dict | None = None) -> tuple[str, str, list[str]]:
    """Combine the deterministic, LLM and inflation layers into one verdict.

    Returns ``(verdict, risk_level, flags)``, where verdict is `low_risk` or
    `high_risk` and risk_level keeps n8n's three-value vocabulary so its Slack
    routing still has the distinction it needs. This deliberately reproduces the
    logic in n8n's "Final Risk Assessment" node rather than replacing it: n8n
    normally sends its own `risk_level` and `/api/audit` trusts it, so this is
    the path taken when a caller posts a raw contextual audit with no risk level
    — and it is the executable spec QA (C7) can check the n8n node against.

    C4's outcome is folded in here rather than becoming a fourth verdict value:
    the Receipts row only ever holds `low_risk` or `high_risk`, and "good deal"
    or "policy violation" is reasoning that belongs in `verdict_reason`.
    """
    policy_checks = policy_checks or {}
    contextual_audit = contextual_audit or {}
    approval = policy_checks.get("approval") or {}

    deterministic = list(policy_checks.get("flags") or [])
    contextual = list(contextual_audit.get("risk_factors") or [])
    flags = list(dict.fromkeys(deterministic + contextual))

    assessment = (validation or {}).get("assessment")
    if assessment == "POLICY_VIOLATION":
        flags.append("INFLATION_ADJUSTED_LIMIT_EXCEEDED")
    elif assessment == "OVER_GUIDELINE":
        flags.append("OVER_CATEGORY_GUIDELINE")

    high_risk = (
        policy_checks.get("human_review_required") is True
        or approval.get("cfo_approval_required") is True
        or contextual_audit.get("recommended_action") == "NEEDS_HUMAN_REVIEW"
        or contextual_audit.get("business_relevance") == "LIKELY_PERSONAL"
        or contextual_audit.get("reasonableness") == "UNREASONABLE"
        or assessment == "POLICY_VIOLATION"
    )
    if high_risk:
        return VERDICT_HIGH, "HIGH", flags

    medium_risk = (
        contextual_audit.get(
            "recommended_action") == "NEEDS_EMPLOYEE_EXPLANATION"
        or contextual_audit.get("business_relevance") == "UNCLEAR"
        or contextual_audit.get("reasonableness") in ("QUESTIONABLE",
                                                      "INSUFFICIENT_INFORMATION")
        or _to_float(contextual_audit.get("confidence")) < 0.75
        or assessment == "OVER_GUIDELINE"
    )
    if medium_risk:
        return VERDICT_HIGH, "MEDIUM", flags

    return VERDICT_LOW, "LOW", flags
