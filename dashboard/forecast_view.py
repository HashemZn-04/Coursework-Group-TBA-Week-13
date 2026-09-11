import altair as alt
import pandas as pd
import streamlit as st

from api.audit import global_inflation_rates
from api.forecast import DEFAULT_CATEGORY, forecast_next_month
from api.summary import format_money
from dashboard.spend import UNKNOWN_CURRENCY, currency_key


def latest_inflation() -> float | None:
    try:
        rates, _ = global_inflation_rates()
    except Exception:  # pragma: no cover - the helper already has a fallback
        return None
    return rates[max(rates)] if rates else None


def render_forecast(expenses: pd.DataFrame, currency: str,
                    category: str = DEFAULT_CATEGORY) -> dict:
    label = category.replace("_", " ").lower()
    currency_display = "currency not recorded" if currency == UNKNOWN_CURRENCY else currency
    st.subheader(f"Next month's {label} spend ({currency_display})")

    # Forecast one currency at a time — the model itself refuses on a mixed
    # history rather than summing across currencies, so a currency this page
    # has already decided to look at should never reach it as a mix.
    single_currency = expenses[expenses["currency"].map(currency_key)
                               == currency_key(currency)]
    result = forecast_next_month(single_currency, category=category,
                                 inflation_pct=latest_inflation())
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

        model = result["model"]
        rmse_col, r2_col = st.columns(2)
        rmse_col.metric("Model RMSE", format_money(model["rmse"], code),
                        help="Root-mean-square error of the fitted line "
                             "against the months it was trained on — the "
                             "typical size of the model's miss, in the same "
                             "unit as the forecast.")
        r2_col.metric("R²", "—" if model["r_squared"] is None
                     else f"{model['r_squared']:.2f}",
                     help="Share of month-to-month variation the trend line "
                          "explains. Blank when there is no variance to "
                          "explain (a perfectly flat history).")

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
        # Censored months are drawn as zero because a bar chart has nowhere
        # else to put them, and named in the caption below.
        chart = history.set_index("month")["spend"]
        if result["forecast"] is not None:
            chart = pd.concat(
                [chart, pd.Series({result["forecast_month"]: result["forecast"]})])
        chart_data = chart.reset_index()
        chart_data.columns = ["month", "spend"]
        st.altair_chart(
            alt.Chart(chart_data).mark_bar().encode(
                x=alt.X("month:N", title="Month", sort=None,
                        axis=alt.Axis(labelAngle=-20)),
                y=alt.Y("spend:Q", title=f"Spend ({label})"),
                tooltip=[alt.Tooltip("month:N", title="Month"),
                         alt.Tooltip("spend:Q", title="Spend", format=",.2f")],
            ),
            use_container_width=True,
        )
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
