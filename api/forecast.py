"""
H1 — next-month travel spend forecast (stretch goal, P2).

"Using scikit-learn, build a simple regression model forecasting next month's
travel spend based on historical spend data and current 2026 price volatility",
with a "sanity-checked output range".

The honest starting position, because it decides the whole design: **there is
almost no history to fit.** The Receipts tab holds one travel receipt. A model
that produced a confident number from that would be worse than no model — and
Amara has already been sold exactly that: a tool that "you'd upload it, and then
you'd wait for half an hour, and then it would say unable to fill out details".
Her stated bar is to fail fast and clearly. So this refuses, by name and
immediately, whenever the data cannot carry a forecast, and it says which of the
reasons applies. When there is enough history it fits an ordinary least-squares
line, reports the spread around that line as a range, and puts a naive trailing
average next to it so the model can be checked against the dumbest thing that
could have been done instead (which is what QA's H3 ticket asks for).

Four rules shape the arithmetic.

**A month with no travel claims is a real zero; a month whose travel claims were
never audited is not.** Zero-filling the second kind would drag the line down
with fabricated data — and it is the dominant case on the live sheet, where
seven of eight receipts hold no verdict. Those months are *censored*: excluded
from the fit, counted, and named. This is the same invariant the rest of the
system holds to — a missing verdict is a processing failure, never a value.

**One currency or nothing.** Nothing converts between GBP and USD (Handbook
12.2 wants the rate on the transaction date; no FX source exists), so a history
that mixes them cannot be summed and the model refuses rather than adding them.

**Inflation is a comparator, not a term in the model.** The World Bank series is
annual and roughly a year in arrears; folding a ~3% annual figure into a fit
over a handful of monthly points would be swamped by the noise while implying a
precision that is not there. It earns its place a different way: the trailing
average is also shown uprated to today's money, so "spend is rising" can be told
apart from "prices are rising", which is the same Policy Decay question C4
answers per receipt. The rate is passed in, never fetched here, so this module
does no network I/O at all.

**A perfectly straight history is not certainty.** On a history that fits
exactly, the residual spread is zero and the range would collapse to a single
number presented to a CFO as fact. The band's half-width is floored, and the
floor is ours rather than anybody's policy.
"""

from dataclasses import dataclass

import pandas as pd
from sklearn.linear_model import LinearRegression

from api.policy import VERDICTS, normalise_category

#: The default category. H1 is specifically about travel; the parameter exists
#: because the same arithmetic answers the same question for any category, and
#: `scripts/h1_demo.py` uses it to show that.
DEFAULT_CATEGORY = "TRAVEL"

#: Fewest monthly observations that will be fitted. Three points define a line
#: and leave one degree of freedom; four is the fewest where the spread around
#: the line means anything at all. **Ours, not a figure from the handbook or the
#: interview** — there is no stakeholder position on how much history is enough.
MIN_HISTORY_MONTHS = 4

#: Months of trailing actuals in the naive baseline. Three is the shortest
#: window that is not just "last month" — also ours.
BASELINE_MONTHS = 3

#: Refuse outright past this span rather than materialising the zero-filled
#: months. The SROIE sample spans 2010 to 2026: filling it produces 190
#: fabricated monthly zeros and a "forecast" fitted almost entirely to them.
MAX_HISTORY_SPAN_MONTHS = 60

#: Floor on the half-width of the reported range, as a share of the larger of
#: the forecast and the trailing average. Ours. Without it a history that
#: happens to be perfectly linear reports a zero-width interval, which reads as
#: certainty rather than as a small sample.
MIN_BAND_FRACTION = 0.10

#: Why a forecast was not produced. Each is a sentence the page can show as-is.
REASONS = {
    "NO_TRAVEL_SPEND":
        "No {category} claims are in the sheet at all, so there is nothing to "
        "forecast from.",
    "TRAVEL_SPEND_UNPROCESSED":
        "{unassessed} of {found} {category} claims never completed the audit "
        "pipeline, leaving too few assessed months to fit. Those claims are not "
        "counted as zero spend — nothing assessed them (see the C3 punch list "
        "in ticket_work/epic_3_tickets.md).",
    "MIXED_CURRENCY_HISTORY":
        "The {category} history is in more than one currency ({currencies}) and "
        "nothing in this pipeline converts between them (Handbook 12.2), so the "
        "months cannot be summed.",
    "NO_READABLE_TOTALS":
        "No {category} claim has both a readable date and a readable amount.",
    "SPAN_TOO_WIDE":
        "The {category} claims span {span} months ({first} to {last}), almost "
        "all of them empty. That is a property of the sample data, not a "
        "spending history, so fitting a line to it would be meaningless.",
    "TOO_FEW_MONTHS":
        "Only {months} month(s) of assessed {category} spend are available; "
        "{minimum} are needed before a line means anything.",
}


@dataclass(frozen=True)
class MonthlySpend:
    """One month of the history, and whether it is real.

    `observed` — claims existed and were assessed.
    `empty` — no claims at all that month; a genuine zero, and evidence.
    `censored` — claims existed but none completed the pipeline. Not a zero,
    and excluded from the fit.
    """

    month: str
    spend: float
    receipts: int
    state: str


def monthly_spend(expenses: pd.DataFrame,
                  category: str = DEFAULT_CATEGORY) -> tuple[list, dict]:
    """Monthly totals for one category, plus what had to be left out.

    Returns ``(rows, diagnostics)`` where rows are `MonthlySpend` in month order
    across the whole observed span, and diagnostics carries the currency, the
    counts of claims excluded and why, and the span.
    """
    category = normalise_category(category)
    diagnostics = {"category": category, "found": 0, "unassessed": 0,
                   "unreadable": 0, "currencies": [], "currency": None,
                   "span_months": 0, "first": None, "last": None}

    if expenses is None or expenses.empty:
        return [], diagnostics

    df = expenses[expenses["category"].map(normalise_category) == category].copy()
    diagnostics["found"] = len(df)
    if df.empty:
        return [], diagnostics

    df["_currency"] = (df["currency"].astype("string").fillna("")
                       .str.strip().str.upper())
    diagnostics["currencies"] = sorted(c for c in df["_currency"].unique() if c)
    if len(diagnostics["currencies"]) == 1:
        diagnostics["currency"] = diagnostics["currencies"][0]

    readable = df[df["date"].notna() & df["total"].notna()]
    diagnostics["unreadable"] = len(df) - len(readable)
    if readable.empty:
        return [], diagnostics

    assessed = readable[readable["verdict"].astype("string").isin(list(VERDICTS))]
    diagnostics["unassessed"] = len(readable) - len(assessed)

    months = readable["date"].dt.to_period("M")
    first, last = months.min(), months.max()
    span = (last - first).n + 1
    diagnostics.update(span_months=span, first=str(first), last=str(last))
    if span > MAX_HISTORY_SPAN_MONTHS:
        return [], diagnostics

    all_months = pd.period_range(first, last, freq="M")
    with_claims = set(months.astype(str))
    assessed_by_month = (assessed.assign(_m=assessed["date"].dt.to_period("M").astype(str))
                         .groupby("_m")["total"].agg(["sum", "size"]))

    rows = []
    for period in all_months:
        key = str(period)
        if key in assessed_by_month.index:
            rows.append(MonthlySpend(key, float(assessed_by_month.loc[key, "sum"]),
                                     int(assessed_by_month.loc[key, "size"]),
                                     "observed"))
        elif key in with_claims:
            rows.append(MonthlySpend(key, 0.0, 0, "censored"))
        else:
            rows.append(MonthlySpend(key, 0.0, 0, "empty"))
    return rows, diagnostics


def _refusal(code: str, diagnostics: dict, history: list, **extra) -> dict:
    fields = {**diagnostics, **extra,
              "category": diagnostics["category"].replace("_", " ").lower(),
              "currencies": ", ".join(diagnostics["currencies"]) or "none",
              "span": diagnostics["span_months"]}
    detail = REASONS[code].format(**fields)
    return {
        "forecast": None,
        "forecast_month": extra.get("forecast_month"),
        "reason_code": code,
        "detail": detail,
        "currency": diagnostics["currency"],
        "category": diagnostics["category"],
        "history": [vars(row) for row in history],
        "baseline": None,
        "inflation": None,
        "range": None,
        "model": None,
        "diagnostics": diagnostics,
    }


def forecast_next_month(expenses: pd.DataFrame, as_of: str | None = None,
                        category: str = DEFAULT_CATEGORY,
                        inflation_pct: float | None = None) -> dict:
    """Forecast the coming month's spend for one category, or say why not.

    `as_of` anchors "next month" — pass it (an ISO date, or anything pandas
    reads) so the answer is reproducible; it defaults to the latest month in the
    history, which keeps the function pure and the tests deterministic.

    `inflation_pct` is the latest published annual inflation rate, used only for
    the uprated comparator. Passed in rather than fetched, so this module never
    touches the network and the test suite's no-network guarantee holds.

    Always returns the same keys. `forecast` is None when it refused, and
    `reason_code` says which of `REASONS` applies.
    """
    history, diagnostics = monthly_spend(expenses, category)

    if diagnostics["found"] == 0:
        return _refusal("NO_TRAVEL_SPEND", diagnostics, history)
    if len(diagnostics["currencies"]) > 1:
        return _refusal("MIXED_CURRENCY_HISTORY", diagnostics, history)
    if not history and diagnostics["span_months"] > MAX_HISTORY_SPAN_MONTHS:
        return _refusal("SPAN_TOO_WIDE", diagnostics, history,
                        span=diagnostics["span_months"])
    if not history:
        return _refusal("NO_READABLE_TOTALS", diagnostics, history)

    fittable = [row for row in history if row.state != "censored"]
    if len(fittable) < MIN_HISTORY_MONTHS:
        code = ("TRAVEL_SPEND_UNPROCESSED" if diagnostics["unassessed"]
                else "TOO_FEW_MONTHS")
        return _refusal(code, diagnostics, history,
                        months=len(fittable), minimum=MIN_HISTORY_MONTHS)

    anchor = (pd.Period(pd.Timestamp(as_of), freq="M") if as_of
              else pd.Period(fittable[-1].month, freq="M"))
    target = anchor + 1

    # x is the month's offset from the first fitted month, so a gap in the
    # history is a gap on the x-axis rather than a compressed step.
    origin = pd.Period(fittable[0].month, freq="M")
    x = [[(pd.Period(row.month, freq="M") - origin).n] for row in fittable]
    y = [row.spend for row in fittable]

    model = LinearRegression().fit(x, y)
    steps_ahead = (target - pd.Period(fittable[-1].month, freq="M")).n
    point = float(model.predict([[(target - origin).n]])[0])
    # Spend cannot be negative. A declining history extrapolates below zero
    # eventually; reporting that as a forecast would be arithmetic, not a
    # prediction.
    forecast = max(point, 0.0)

    residuals = [actual - float(pred)
                 for actual, pred in zip(y, model.predict(x))]
    dof = max(len(fittable) - 2, 1)
    variance = sum(r * r for r in residuals) / dof
    residual_std = variance ** 0.5

    total_ss = sum((value - sum(y) / len(y)) ** 2 for value in y)
    r_squared = (None if total_ss == 0
                 else 1 - sum(r * r for r in residuals) / total_ss)

    trailing = [row.spend for row in fittable[-BASELINE_MONTHS:]]
    baseline = sum(trailing) / len(trailing)

    # The band widens with the horizon — projecting four months past the last
    # observation is a weaker claim than projecting one, and a band that ignored
    # that would say otherwise. The square root is ours: it is the shape
    # uncertainty takes when errors accumulate independently, not a figure
    # anybody in this project set.
    #
    # The floor is measured against the larger of the forecast and the trailing
    # average, not against the forecast alone. A declining history can clamp the
    # forecast to zero, and a floor taken as a fraction of zero is zero — which
    # would report "£0.00 to £0.00" as though the model were certain, on exactly
    # the input it understands least.
    half_width = max(1.96 * residual_std * (steps_ahead ** 0.5),
                     MIN_BAND_FRACTION * max(forecast, baseline))
    inflation = None
    if inflation_pct is not None:
        monthly_rate = (1 + inflation_pct / 100) ** (1 / 12) - 1
        inflation = {
            "annual_pct": inflation_pct,
            "uprated_baseline": round(baseline * (1 + monthly_rate) ** steps_ahead, 2),
            "note": ("The trailing average restated in the forecast month's "
                     "money, so a rise in spend can be told apart from a rise "
                     "in prices. The series is annual and about a year in "
                     "arrears, so this understates rather than overstates."),
        }

    return {
        "forecast": round(forecast, 2),
        "forecast_month": str(target),
        "reason_code": None,
        "detail": (f"Fitted on {len(fittable)} month(s) of assessed "
                   f"{diagnostics['category'].replace('_', ' ').lower()} spend "
                   f"({fittable[0].month} to {fittable[-1].month}), projected "
                   f"{steps_ahead} month(s) forward."),
        "currency": diagnostics["currency"],
        "category": diagnostics["category"],
        "history": [vars(row) for row in history],
        "baseline": {"months": len(trailing), "value": round(baseline, 2)},
        "inflation": inflation,
        "range": {"low": round(max(forecast - half_width, 0.0), 2),
                  "high": round(forecast + half_width, 2),
                  "basis": ("Ordinary least squares, ±1.96 standard deviations "
                            "of the fit's own residuals, widened by the square "
                            "root of how many months ahead this reaches, and "
                            f"floored at {MIN_BAND_FRACTION:.0%} of the larger "
                            "of the forecast and the trailing average — so "
                            "neither a perfectly linear history nor a forecast "
                            "clamped at zero can read as certainty.")},
        "model": {"method": "sklearn.linear_model.LinearRegression",
                  "slope_per_month": round(float(model.coef_[0]), 2),
                  "intercept": round(float(model.intercept_), 2),
                  "r_squared": None if r_squared is None else round(r_squared, 4),
                  "months_fitted": len(fittable),
                  "steps_ahead": steps_ahead,
                  "residual_std": round(residual_std, 2)},
        "diagnostics": diagnostics,
    }
