"""
H2 — the forecast on the dashboard (stretch goal, P2).

"Dashboard shows a forecasted next-month travel spend figure alongside
historical actuals". The ticket's own suggestion is "a forecast line alongside
actual spend in E2", so this renders as a section of Spend Overview rather than
a page of its own — a forecast belongs next to the actuals it extends.

Everything numeric comes from `api.forecast`; this file only decides how to say
it. In particular, when the model refuses it prints the model's own sentence.
Amara's complaint about the last tool she was sold was that it made her wait and
then told her nothing useful — so a refusal here is immediate, names what is
missing, and still draws whatever history exists.
"""

import pandas as pd
import streamlit as st

from api.audit import global_inflation_rates
from api.forecast import DEFAULT_CATEGORY, forecast_next_month
from api.summary import format_money


def _latest_inflation() -> float | None:
    """Latest published annual global inflation, or None if unavailable.

    `global_inflation_rates` is `lru_cache`d and falls back to a pinned snapshot
    when the World Bank cannot be reached, so this costs at most one HTTP call
    per process and never fails the page.
    """
    try:
        rates, _ = global_inflation_rates()
    except Exception:  # pragma: no cover - the helper already has a fallback
        return None
    return rates[max(rates)] if rates else None


def render_forecast(expenses: pd.DataFrame, currency: str,
                    category: str = DEFAULT_CATEGORY) -> dict:
    """Draw the forecast section. Returns the model's result for testability."""
    label = category.replace("_", " ").lower()
    st.subheader(f"Next month's {label} spend")

    result = forecast_next_month(expenses, category=category,
                                 inflation_pct=_latest_inflation())
    history = pd.DataFrame(result["history"])

    if result["forecast"] is None:
        st.info(f"**No forecast.** {result['detail']}")
    else:
        code = result["currency"] or currency
        point, band, baseline = st.columns(3)
        point.metric(f"Forecast — {result['forecast_month']}",
                     format_money(result["forecast"], code))
        band.metric("Indicative range",
                    f"{format_money(result['range']['low'], code)} – "
                    f"{format_money(result['range']['high'], code)}")
        baseline.metric(f"Last {result['baseline']['months']} months, average",
                        format_money(result["baseline"]["value"], code))
        st.caption(f"{result['detail']} {result['range']['basis']}")
        if result["inflation"]:
            st.caption(
                f"For comparison, that trailing average restated in "
                f"{result['forecast_month']} money at the latest published "
                f"global inflation rate "
                f"({result['inflation']['annual_pct']:.1f}% a year) is "
                f"{format_money(result['inflation']['uprated_baseline'], code)}. "
                f"{result['inflation']['note']}"
            )

    if not history.empty:
        # Censored months are drawn as zero because a bar chart has nowhere else
        # to put them, so they are named underneath rather than left to look
        # like quiet months.
        chart = history.set_index("month")["spend"]
        if result["forecast"] is not None:
            chart = pd.concat(
                [chart, pd.Series({result["forecast_month"]: result["forecast"]})])
        st.bar_chart(chart)
        censored = int((history["state"] == "censored").sum())
        empty = int((history["state"] == "empty").sum())
        parts = [f"Monthly {label} actuals"]
        if result["forecast"] is not None:
            parts.append(f"with {result['forecast_month']} as the forecast")
        caption = ", ".join(parts) + "."
        if censored:
            caption += (f" {censored} month(s) held {label} claims that never "
                        f"completed the audit pipeline — drawn as zero because "
                        f"a bar has nowhere else to sit, but excluded from the "
                        f"fit. They are not months with no spend.")
        if empty:
            caption += f" {empty} month(s) had no {label} claims at all."
        st.caption(caption)

    st.caption(
        "Method: ordinary least squares over monthly totals "
        "(`sklearn.linear_model.LinearRegression`), fitted only to months whose "
        "claims completed the audit pipeline. Inflation is shown as a "
        "comparator, not folded into the fit — the series is annual and about a "
        "year in arrears, and a ~3% figure inside a fit over a handful of "
        "monthly points implies a precision that is not there."
    )
    return result
