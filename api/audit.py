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

# n8n computes three risk levels to pick between three Slack replies; we store
# two verdicts. MEDIUM ("needs an explanation") maps to high_risk.
RISK_TO_VERDICT = {"HIGH": VERDICT_HIGH, "MEDIUM": VERDICT_HIGH,
                   "LOW": VERDICT_LOW}


def map_verdict(risk_level: str) -> str:
    return RISK_TO_VERDICT.get(str(risk_level).strip().upper(), VERDICT_HIGH)


# --------------------------------------------------------------------------- #
# Global inflation
# --------------------------------------------------------------------------- #

WORLD_BANK_URL = ("https://api.worldbank.org/v2/country/WLD/"
                  "indicator/FP.CPI.TOTL.ZG")
WORLD_BANK_TIMEOUT = 15
CPI_SERIES_ID = "WLD.FP.CPI.TOTL.ZG"

# Fallback used when the World Bank API is unreachable, captured 2026-09-09.
# Full published precision, not rounded, so the offline demo matches the live one.
GLOBAL_INFLATION_FALLBACK: dict[int, float] = {
    2015: 1.43702380935655, 2016: 1.59691227583204, 2017: 2.22314331448899,
    2018: 2.44258329692817, 2019: 2.20607305781525, 2020: 1.90509722047501,
    2021: 3.47540320289875, 2022: 8.08169507021982, 2023: 5.79944107391962,
    2024: 3.01447576977999, 2025: 3.0414132155654,
}


@lru_cache(maxsize=1)
def global_inflation_rates() -> tuple[dict[int, float], str]:
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


def price_index(rates: dict[int, float]) -> tuple[dict[int, float], float]:
    # Level at the start of each year, anchored at 100. Start-of-year for the
    # base matters: the handbook was issued March 2019, so nearly all of that
    # year's inflation applies to it.
    index, level = {}, 100.0
    for year in sorted(rates):
        index[year] = level
        level *= 1 + rates[year] / 100
    return index, level


def year_of(period: str | int) -> int:
    return int(str(period)[:4])


@lru_cache(maxsize=32)
def cpi_for(period: str | int | None = None) -> tuple[str, float, str]:
    rates, source = global_inflation_rates()
    index, end_level = price_index(rates)
    last_year = max(rates)
    if period is None:
        return str(last_year), round(end_level, 4), source
    year = min(max(year_of(period), min(index)), last_year)  # clamp to series
    return str(year), round(index[year], 4), source


def latest_cpi() -> float:
    return cpi_for(None)[1]


def inflation_factor(base_period: str) -> tuple[float, dict]:
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
    factor, _ = inflation_factor(base_period)
    return round(static_limit * factor, 2)


# --------------------------------------------------------------------------- #
# C4 — contextual validation
# --------------------------------------------------------------------------- #

def contextual_validation(total: float, category: str, units: int = 1,
                          currency: str | None = None) -> dict:
    category = normalise_category(category)
    amount = to_float(total)
    limit = limit_for(category)

    if limit is None:
        return {
            "category": category,
            "assessment": "NO_LIMIT",
            "static_limit": None,
            "adjusted_limit": None,
            "detail": (
                f"The handbook sets no numeric limit for {category_label(category)}; "
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
    # Guard the pathological case of a deflating index re-pricing stricter.
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
        "detail": validation_detail(assessment, limit, unit_amount, adjusted,
                                     factor, currency, unconverted),
    }


def validation_detail(assessment: str, limit: Limit, unit_amount: float,
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


def category_label(category: str) -> str:
    return category.replace("_", " ").lower()


def to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# Risk assembly — mirrors n8n's "Final Risk Assessment" node
# --------------------------------------------------------------------------- #

def final_verdict(policy_checks: dict, contextual_audit: dict,
                  validation: dict | None = None) -> tuple[str, str, list[str]]:
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
        or to_float(contextual_audit.get("confidence")) < 0.75
        or assessment == "OVER_GUIDELINE"
    )
    if medium_risk:
        return VERDICT_HIGH, "MEDIUM", flags

    return VERDICT_LOW, "LOW", flags
