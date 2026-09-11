from dataclasses import dataclass

import pandas as pd
from sklearn.linear_model import LinearRegression

from api.policy import VERDICTS, normalise_category

DEFAULT_CATEGORY = "TRAVEL"

# Fewest monthly observations that will be fitted. Three points define a line
# and leave one degree of freedom; four is the fewest where the spread means
# anything.
MIN_HISTORY_MONTHS = 4

# Months of trailing actuals in the naive baseline.
BASELINE_MONTHS = 3

# How many months ahead of the anchor month the *headline* forecast targets —
# the big number, the indicative range, and RMSE/R² all describe this one
# month. Kept at 1 so the dashboard's focal point is "next month", the
# shortest (and least uncertain) horizon the model can speak to.
FOCAL_HORIZON_MONTHS = 1

# How many months ahead the model projects and the chart plots in total
# (1..FORECAST_HORIZON_MONTHS). Widened from 1 to 3 once the sheet held
# enough history for a longer horizon to be worth plotting — the months past
# FOCAL_HORIZON_MONTHS are shown on the chart for context, in a secondary
# colour, without their own headline number or RMSE/R².
FORECAST_HORIZON_MONTHS = 3

# Refuse outright past this span rather than materialising zero-filled months.
MAX_HISTORY_SPAN_MONTHS = 60

# Floor on the half-width of the reported range, as a share of the larger of
# the forecast and the trailing average — otherwise a perfectly linear history
# reports a zero-width interval, which reads as certainty.
MIN_BAND_FRACTION = 0.10

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
    """state: observed (assessed claims), empty (no claims), or censored
    (claims existed but none completed the pipeline — excluded from the fit)."""

    month: str
    spend: float
    receipts: int
    state: str


def monthly_spend(expenses: pd.DataFrame,
                  category: str = DEFAULT_CATEGORY) -> tuple[list, dict]:
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


def build_refusal(code: str, diagnostics: dict, history: list, **extra) -> dict:
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
        "horizons": None,
        "model": None,
        "diagnostics": diagnostics,
    }


def forecast_next_month(expenses: pd.DataFrame, as_of: str | None = None,
                        category: str = DEFAULT_CATEGORY,
                        inflation_pct: float | None = None) -> dict:
    history, diagnostics = monthly_spend(expenses, category)

    if diagnostics["found"] == 0:
        return build_refusal("NO_TRAVEL_SPEND", diagnostics, history)
    if len(diagnostics["currencies"]) > 1:
        return build_refusal("MIXED_CURRENCY_HISTORY", diagnostics, history)
    if not history and diagnostics["span_months"] > MAX_HISTORY_SPAN_MONTHS:
        return build_refusal("SPAN_TOO_WIDE", diagnostics, history,
                        span=diagnostics["span_months"])
    if not history:
        return build_refusal("NO_READABLE_TOTALS", diagnostics, history)

    fittable = [row for row in history if row.state != "censored"]
    if len(fittable) < MIN_HISTORY_MONTHS:
        code = ("TRAVEL_SPEND_UNPROCESSED" if diagnostics["unassessed"]
                else "TOO_FEW_MONTHS")
        return build_refusal(code, diagnostics, history,
                        months=len(fittable), minimum=MIN_HISTORY_MONTHS)

    anchor = (pd.Period(pd.Timestamp(as_of), freq="M") if as_of
              else pd.Period(fittable[-1].month, freq="M"))

    # x is the month's offset from the first fitted month, so a gap in the
    # history is a gap on the x-axis rather than a compressed step.
    origin = pd.Period(fittable[0].month, freq="M")
    x = [[(pd.Period(row.month, freq="M") - origin).n] for row in fittable]
    y = [row.spend for row in fittable]

    model = LinearRegression().fit(x, y)

    # The fit itself — residuals, RMSE, R² — doesn't depend on how far ahead
    # any particular forecast reaches, only on how well the line matches the
    # months it was trained on. Computed once and reused for every horizon.
    residuals = [actual - float(pred)
                 for actual, pred in zip(y, model.predict(x))]
    dof = max(len(fittable) - 2, 1)
    variance = sum(r * r for r in residuals) / dof
    residual_std = variance ** 0.5
    rmse = (sum(r * r for r in residuals) / len(residuals)) ** 0.5

    mean_y = sum(y) / len(y)
    # RMSE relative to the average month fitted, so the miss can be read as a
    # share of typical spend rather than in currency, and compared across
    # currencies and categories on the same scale.
    rmse_pct = None if mean_y == 0 else (rmse / mean_y) * 100

    total_ss = sum((value - mean_y) ** 2 for value in y)
    r_squared = (None if total_ss == 0
                 else 1 - sum(r * r for r in residuals) / total_ss)

    trailing = [row.spend for row in fittable[-BASELINE_MONTHS:]]
    baseline = sum(trailing) / len(trailing)

    def horizon_at(months_ahead: int) -> dict:
        target = anchor + months_ahead
        steps_ahead = (target - pd.Period(fittable[-1].month, freq="M")).n
        point = float(model.predict([[(target - origin).n]])[0])
        forecast = max(point, 0.0)  # spend cannot be negative
        # Band widens with the horizon (sqrt of steps ahead) and is floored
        # against the larger of forecast/baseline, so a forecast clamped to
        # zero can't read as certainty.
        half_width = max(1.96 * residual_std * (steps_ahead ** 0.5),
                         MIN_BAND_FRACTION * max(forecast, baseline))
        return {
            "months_ahead": months_ahead,
            "forecast_month": str(target),
            "steps_ahead": steps_ahead,
            "forecast": round(forecast, 2),
            "range": {"low": round(max(forecast - half_width, 0.0), 2),
                      "high": round(forecast + half_width, 2)},
        }

    # One entry per month ahead, 1..FORECAST_HORIZON_MONTHS — the dashboard
    # headlines FOCAL_HORIZON_MONTHS and plots the rest for context.
    horizons = [horizon_at(h) for h in range(1, FORECAST_HORIZON_MONTHS + 1)]
    focal = horizons[FOCAL_HORIZON_MONTHS - 1]

    inflation = None
    if inflation_pct is not None:
        monthly_rate = (1 + inflation_pct / 100) ** (1 / 12) - 1
        inflation = {
            "annual_pct": inflation_pct,
            "uprated_baseline": round(
                baseline * (1 + monthly_rate) ** focal["steps_ahead"], 2),
            "note": ("The trailing average restated in the forecast month's "
                     "money, so a rise in spend can be told apart from a rise "
                     "in prices. The series is annual and about a year in "
                     "arrears, so this understates rather than overstates."),
        }

    return {
        "forecast": focal["forecast"],
        "forecast_month": focal["forecast_month"],
        "reason_code": None,
        "detail": (f"Fitted on {len(fittable)} month(s) of assessed "
                   f"{diagnostics['category'].replace('_', ' ').lower()} spend "
                   f"({fittable[0].month} to {fittable[-1].month}), projected "
                   f"{focal['steps_ahead']} month(s) forward."),
        "currency": diagnostics["currency"],
        "category": diagnostics["category"],
        "history": [vars(row) for row in history],
        "baseline": {"months": len(trailing), "value": round(baseline, 2)},
        "inflation": inflation,
        "range": {**focal["range"],
                  "basis": ("Ordinary least squares, ±1.96 standard deviations "
                            "of the fit's own residuals, widened by the square "
                            "root of how many months ahead this reaches, and "
                            f"floored at {MIN_BAND_FRACTION:.0%} of the larger "
                            "of the forecast and the trailing average — so "
                            "neither a perfectly linear history nor a forecast "
                            "clamped at zero can read as certainty.")},
        # Every horizon 1..FORECAST_HORIZON_MONTHS, for the chart — the
        # dashboard's headline number/range/RMSE/R² all describe `focal`
        # (months_ahead == FOCAL_HORIZON_MONTHS) only.
        "horizons": horizons,
        "model": {"method": "sklearn.linear_model.LinearRegression",
                  "slope_per_month": round(float(model.coef_[0]), 2),
                  "intercept": round(float(model.intercept_), 2),
                  "r_squared": None if r_squared is None else round(r_squared, 4),
                  "months_fitted": len(fittable),
                  "steps_ahead": focal["steps_ahead"],
                  "residual_std": round(residual_std, 2),
                  "rmse": round(rmse, 2),
                  "rmse_pct": None if rmse_pct is None else round(rmse_pct, 2)},
        "diagnostics": diagnostics,
    }
