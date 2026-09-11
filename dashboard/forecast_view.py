import altair as alt
import pandas as pd
import streamlit as st

from api.audit import global_inflation_rates
from api.forecast import (DEFAULT_CATEGORY, FOCAL_HORIZON_MONTHS,
                          FORECAST_HORIZON_MONTHS, forecast_next_month)
from api.summary import format_money
from dashboard.spend import UNKNOWN_CURRENCY, currency_key

# Chart series labels/colours for the actuals bar plus the two forecast
# bands: the headline (focal) month in red, the remaining plotted months in
# purple as context only — they get no RMSE/R² of their own. Colours are
# validated together for colourblind-safe separation (dataviz skill's
# categorical dark-mode slots: blue/red/violet); "Actual" reuses the
# dashboard's existing default bar blue.
_FOCAL_KIND = f"{FOCAL_HORIZON_MONTHS}-month forecast"
_CONTEXT_KIND = (f"{FOCAL_HORIZON_MONTHS + 1}–{FORECAST_HORIZON_MONTHS} month forecast"
                 if FORECAST_HORIZON_MONTHS > FOCAL_HORIZON_MONTHS else None)
CHART_KINDS = ["Actual", _FOCAL_KIND] + ([_CONTEXT_KIND] if _CONTEXT_KIND else [])
CHART_COLORS = ["#3987e5", "#e66767", "#9085e9"][:len(CHART_KINDS)]


def latest_inflation() -> float | None:
    try:
        rates, _ = global_inflation_rates()
    except Exception:  # pragma: no cover - the helper already has a fallback
        return None
    return rates[max(rates)] if rates else None


def _markdown_safe_money_range(low: str, high: str) -> str:
    """`st.metric` renders its value as Markdown, and two literal `$` in one
    string — e.g. two USD amounts either side of an en dash — get parsed as
    inline LaTeX math instead of currency, rendering as a raw, unstyled
    `0.00 –` fragment. Backslash-escaping `$` is a no-op for £/€ and for
    Markdown rendering (it still displays as a plain `$`), but stops the
    math parser from treating the pair as delimiters."""
    return f"{low} – {high}".replace("$", "\\$")


def render_forecast(expenses: pd.DataFrame, currency: str,
                    category: str = DEFAULT_CATEGORY) -> dict:
    label = category.replace("_", " ").lower()
    currency_display = "currency not recorded" if currency == UNKNOWN_CURRENCY else currency
    horizon_phrase = ("Next month's" if FOCAL_HORIZON_MONTHS == 1
                      else f"{FOCAL_HORIZON_MONTHS}-month-ahead")
    st.subheader(f"{horizon_phrase} {label} spend ({currency_display})")

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
        point, baseline = st.columns(2)
        point.metric(f"Forecast — {result['forecast_month']}",
                     format_money(result["forecast"], code))
        baseline.metric(f"Last {result['baseline']['months']} months, average",
                        format_money(result["baseline"]["value"], code))
        # Its own full-width row rather than a third column — two currency
        # amounts joined by an en dash routinely overflow a one-third-width
        # metric and get truncated.
        st.metric("Indicative range", _markdown_safe_money_range(
            format_money(result["range"]["low"], code),
            format_money(result["range"]["high"], code)))

        model = result["model"]
        rmse_col, r2_col = st.columns(2)
        rmse_display = ("—" if model["rmse_pct"] is None
                        else f"{model['rmse_pct']:.1f}%")
        rmse_col.metric("Model RMSE", rmse_display,
                        help="Root-mean-square error of the fitted line "
                             "against the months it was trained on, as a "
                             "share of the average month's spend in the fit "
                             "— the typical size of the model's miss, "
                             "comparable across currencies and categories.")
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
        chart_data = history.set_index("month")["spend"].reset_index()
        chart_data.columns = ["month", "spend"]
        chart_data["kind"] = "Actual"

        has_forecast = result["forecast"] is not None
        if has_forecast:
            # One bar per plotted horizon (1..FORECAST_HORIZON_MONTHS) —
            # red for the focal month the headline number/range/RMSE/R²
            # describe, purple for the rest, shown for context only.
            horizon_rows = pd.DataFrame([
                {"month": h["forecast_month"], "spend": h["forecast"],
                 "kind": (_FOCAL_KIND if h["months_ahead"] == FOCAL_HORIZON_MONTHS
                          else _CONTEXT_KIND)}
                for h in result["horizons"]
            ])
            chart_data = pd.concat([chart_data, horizon_rows], ignore_index=True)

        encoding = dict(
            x=alt.X("month:N", title="Month", sort=None,
                    axis=alt.Axis(labelAngle=-20)),
            y=alt.Y("spend:Q", title=f"Spend ({label})"),
            tooltip=[alt.Tooltip("month:N", title="Month"),
                     alt.Tooltip("spend:Q", title="Spend", format=",.2f")],
        )
        if has_forecast:
            # A legend only makes sense once there's more than one series —
            # a history-only chart stays a single, uncoloured bar colour.
            encoding["color"] = alt.Color(
                "kind:N", sort=CHART_KINDS,
                scale=alt.Scale(domain=CHART_KINDS, range=CHART_COLORS),
                legend=alt.Legend(title=None, orient="top"))
            encoding["tooltip"] = encoding["tooltip"] + [
                alt.Tooltip("kind:N", title="Series")]

        st.altair_chart(
            alt.Chart(chart_data).mark_bar().encode(**encoding),
            use_container_width=True,
        )
        censored = int((history["state"] == "censored").sum())
        empty = int((history["state"] == "empty").sum())
        parts = [f"Monthly {label} actuals"]
        if has_forecast:
            parts.append(
                f"with {result['forecast_month']} as the {_FOCAL_KIND} (red) "
                + ("and the following months shown in purple for context only"
                   if _CONTEXT_KIND else ""))
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
