"""
C4 — Contextual Validation, inflation-aware (MCP-27), plus the verdict mapping
C3/C5 share.

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

CPI comes from FRED (ticket C2 names FRED or BLS). C2 — AA's scheduled pull —
is not built yet, so `cpi_for()` calls FRED directly and caches per process,
which stands in for the cron job. When C2 lands, point `cpi_for` at the
Benchmarks tab; nothing else in this module changes.
"""

import os
from functools import lru_cache

import requests
from dotenv import load_dotenv

try:  # importable both as `api.audit` and as a sibling of `app.py`
    from api.policy import (APPROVAL_THRESHOLDS, REPORTING_CURRENCY, Limit,
                            limit_for, normalise_category)
    from api.summary import format_money
except ImportError:  # pragma: no cover - exercised only by `python api/app.py`
    from policy import (APPROVAL_THRESHOLDS, REPORTING_CURRENCY, Limit,
                        limit_for, normalise_category)
    from summary import format_money

load_dotenv()

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_TIMEOUT = 10

#: US all-items CPI. Overridable, but note the UK alternative on FRED
#: (GBRCPIALLMINMEI) stops in early 2025 and so cannot answer a 2026 question.
CPI_SERIES_ID = os.environ.get("CPI_SERIES_ID", "CPIAUCSL")

#: Observations captured 2026-09-09 so a demo without network or without a
#: FRED_API_KEY still produces a defensible number instead of a stack trace.
#: Every result says which source it used, so a fallback is never silent.
CPI_FALLBACK: dict[str, tuple[str, float]] = {
    "latest": ("2026-07-01", 332.813),
    "2019-03-01": ("2019-03-01", 254.277),
    "2020-04-01": ("2020-04-01", 256.032),
    "2022-01-01": ("2022-01-01", 282.543),
}

RISK_TO_VERDICT = {"HIGH": "high_risk", "MEDIUM": "flagged", "LOW": "compliant"}
VERDICT_TO_RISK = {v: k for k, v in RISK_TO_VERDICT.items()}


def map_verdict(risk_level: str) -> str:
    """n8n's risk level -> the verdict vocabulary stored in the Verdicts tab."""
    return RISK_TO_VERDICT.get(str(risk_level).strip().upper(), "compliant")


# --------------------------------------------------------------------------- #
# CPI lookup (stands in for C2's scheduled pull until AA builds it)
# --------------------------------------------------------------------------- #

def _fred_observations(params: dict) -> list[dict]:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set")
    response = requests.get(
        FRED_URL,
        params={"series_id": CPI_SERIES_ID, "api_key": api_key,
                "file_type": "json", **params},
        timeout=FRED_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("observations", [])


def _first_valid(observations: list[dict]) -> tuple[str, float]:
    """FRED writes missing observations as ".", so skip to the first real one."""
    for observation in observations:
        try:
            return observation["date"], float(observation["value"])
        except (KeyError, TypeError, ValueError):
            continue
    raise ValueError("no usable CPI observation in FRED response")


@lru_cache(maxsize=32)
def cpi_for(period: str | None = None) -> tuple[str, float, str]:
    """CPI index level for a month, as ``(observation_date, value, source)``.

    `period` is a FRED observation date (month start, e.g. ``"2019-03-01"``);
    None means "the most recent published observation". A month with no
    published figure falls forward to the next available one within a quarter,
    which matters for base periods near the end of the series.

    `source` is ``"fred"`` for a live call or ``"fallback"`` for the pinned
    snapshot above — callers surface it so a cached number is never mistaken for
    a live one.
    """
    try:
        if period is None:
            date, value = _first_valid(
                _fred_observations({"sort_order": "desc", "limit": 1}))
        else:
            end = _quarter_end(period)
            date, value = _first_valid(_fred_observations(
                {"observation_start": period, "observation_end": end}))
        return date, value, "fred"
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        date, value = CPI_FALLBACK.get(period or "latest", CPI_FALLBACK["latest"])
        return date, value, "fallback"


def _quarter_end(period: str) -> str:
    """Three months after `period`, so a missing month can fall forward."""
    year, month, _ = (int(part) for part in period.split("-"))
    month += 3
    year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    return f"{year:04d}-{month:02d}-01"


def latest_cpi() -> float:
    """Most recent CPI index level. Kept as the simple form used in the guide."""
    return cpi_for(None)[1]


def inflation_factor(base_period: str) -> tuple[float, dict]:
    """How much prices have moved since `base_period`, plus the CPI provenance."""
    base_date, base_value, base_source = cpi_for(base_period)
    latest_date, latest_value, latest_source = cpi_for(None)
    provenance = {
        "series_id": CPI_SERIES_ID,
        "base_period": base_date,
        "base_value": base_value,
        "latest_period": latest_date,
        "latest_value": latest_value,
        # "fred" only when *both* lookups were live.
        "source": "fred" if base_source == latest_source == "fred" else "fallback",
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

    unconverted = bool(currency) and str(currency).upper() != REPORTING_CURRENCY
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

    Returns ``(verdict, risk_level, flags)``. This deliberately reproduces the
    logic in n8n's "Final Risk Assessment" node rather than replacing it: n8n
    normally sends its own `risk_level` and `/api/audit` trusts it, so this is
    the path taken when a caller posts a raw contextual audit with no risk level
    — and it is the executable spec QA (C7) can check the n8n node against.

    C4's outcome is folded in here rather than becoming a fourth verdict value:
    the Verdicts tab only ever holds compliant / flagged / high_risk, and
    "good deal" or "policy violation" is reasoning that belongs in `reason`.
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
        return "high_risk", "HIGH", flags

    medium_risk = (
        contextual_audit.get("recommended_action") == "NEEDS_EMPLOYEE_EXPLANATION"
        or contextual_audit.get("business_relevance") == "UNCLEAR"
        or contextual_audit.get("reasonableness") in ("QUESTIONABLE",
                                                      "INSUFFICIENT_INFORMATION")
        or _to_float(contextual_audit.get("confidence")) < 0.75
        or assessment == "OVER_GUIDELINE"
    )
    if medium_risk:
        return "flagged", "MEDIUM", flags

    return "compliant", "LOW", flags
