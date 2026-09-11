import altair as alt
import streamlit as st

from api.policy import normalise_category
from api.summary import format_money
from dashboard.data import load_expenses
from dashboard.forecast_view import render_forecast
from dashboard.spend import (UNKNOWN_CURRENCY, default_currency,
                             prevented_running_total, spend_over_time,
                             spend_summary)

st.title("Spend Overview")

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

summary = spend_summary(df)
currencies = summary.currencies


def currency_label(code: str) -> str:
    return "Currency not recorded" if code == UNKNOWN_CURRENCY else code


# Nothing in this pipeline converts between currencies (Handbook 12.2), so
# totals are shown per currency and never added together.
if len(currencies) > 1:
    st.caption(
        "Totals are shown per currency. Nothing here converts between them "
        "(Handbook 12.2 wants the rate on the transaction date; no exchange-rate "
        "source is wired in), so weigh the rate and local purchasing power "
        "yourself before comparing the rows."
    )

summary_code = st.selectbox(
    "Currency", currencies, format_func=currency_label, key="currency_summary",
    index=currencies.index(default_currency(currencies)))
row = summary.totals.loc[summary_code]

claimed, approved, at_risk, prevented = st.columns(4)
claimed.metric("Claimed", format_money(row["claimed"], summary_code),
               help="Everything submitted, whatever happened to it next — "
                    "including claims still awaiting a decision and claims "
                    "the pipeline never processed.")
claimed.caption(f"{int(row['claimed_count'])} claims")

approved.metric("Approved", format_money(row["approved"], summary_code),
                help="Claims with a standing approval — yours, or the "
                     "engine's automatic approval of a low-risk claim. "
                     "This money is payable.")
approved.caption(f"{int(row['approved_count'])} claims")

at_risk.metric("At risk · awaiting your decision",
               format_money(row["at_risk"], summary_code),
               help="High-risk claims with no decision recorded. This is "
                    "money at risk, not money saved — nothing is prevented "
                    "until you reject it.")
at_risk.caption(f"{int(row['at_risk_count'])} claims")

prevented.metric("Leakage prevented", format_money(row["prevented"], summary_code),
                 help="Claims you rejected, so the money was not paid out.")
prevented.caption(f"{int(row['prevented_count'])} claims")

st.caption(
    "**At risk** is money still on the table — claims flagged and not yet "
    "decided. **Leakage prevented** is money already stopped — claims you "
    "rejected. They are different numbers, and only the second one is a saving."
)

if not summary.totals["prevented_count"].any():
    st.info(
        "No claim has been rejected yet, so nothing has been prevented yet. "
        "This figure moves the first time you reject a claim in the Review Queue."
    )

# A receipt holding neither verdict never completed the pipeline — a
# processing failure, not a third category. It's inside Claimed and in none
# of the outcome tiles.
unprocessed_count = int(summary.totals["unprocessed_count"].sum())
if unprocessed_count:
    amounts = "; ".join(
        format_money(summary.totals.loc[code, "unprocessed"], code)
        for code in currencies if summary.totals.loc[code, "unprocessed_count"])
    st.error(
        f"**{unprocessed_count} of {len(df)} receipts never completed the audit "
        f"pipeline.** Every receipt should end up either auto-approved or in the "
        f"review queue — these are in neither, which means the pipeline did not "
        f"run for them. They are inside *Claimed* and in none of the outcome "
        f"tiles: nothing has assessed them, so they are neither approved, at "
        f"risk, nor prevented. Amount involved: {amounts}."
    )

integrity = []
if summary.duplicate_receipt_ids:
    integrity.append(
        f"{summary.duplicate_receipt_ids} receipt(s) share an id with another "
        f"row, so a decision cannot be attached to one of them with certainty. "
        f"They are counted in *Claimed* and in no outcome tile."
    )
if summary.undated_rejections:
    integrity.append(
        f"{summary.undated_rejections} rejection(s) have no readable decision "
        f"date. They are in the total but not on the running-total chart."
    )
if int(summary.totals["unrecognised_count"].sum()):
    integrity.append(
        f"{int(summary.totals['unrecognised_count'].sum())} receipt(s) carry a "
        f"verdict that is neither `low_risk` nor `high_risk`. Fix the value in "
        f"the Receipts tab."
    )
if integrity:
    st.warning("**Data integrity**\n\n" +
               "\n\n".join(f"- {line}" for line in integrity))

st.subheader("Spend velocity")
velocity_code = st.selectbox(
    "Currency", currencies, format_func=currency_label, key="currency_velocity",
    index=currencies.index(default_currency(currencies)))
timeline = spend_over_time(df, velocity_code)
if timeline.empty:
    st.info(f"No receipt in {currency_label(velocity_code)} has a readable date, so "
            f"there is nothing to plot over time.")
else:
    chart_data = timeline.reset_index()
    st.altair_chart(
        alt.Chart(chart_data).mark_bar().encode(
            x=alt.X("date:T", title="Period"),
            y=alt.Y("spend:Q", title=f"Spend ({currency_label(velocity_code)})"),
            tooltip=[alt.Tooltip("date:T", title="Period"),
                     alt.Tooltip("spend:Q", title="Spend", format=",.2f"),
                     alt.Tooltip("receipts:Q", title="Claims")],
        ),
        use_container_width=True,
    )
    grain = {"D": "day", "W": "week", "MS": "month", "QS": "quarter",
             "YS": "year"}
    freq = timeline.index.freqstr or ""
    st.caption(
        f"Spend per {grain.get(freq.split('-')[0], 'period')}, in "
        f"{currency_label(velocity_code)} — {int(timeline['receipts'].sum())} claims "
        f"across {len(timeline)} periods. Periods with no claims are drawn as "
        f"zero, because a quiet month is a fact about velocity."
    )
undated = int(df["date"].isna().sum())
if undated:
    st.caption(f"{undated} receipt(s) omitted — no readable date.")

st.subheader("Leakage prevented, running total")
running_total_code = st.selectbox(
    "Currency", currencies, format_func=currency_label, key="currency_running_total",
    index=currencies.index(default_currency(currencies)))
running = prevented_running_total(df, running_total_code)
if running.empty:
    st.info(f"Nothing rejected in {currency_label(running_total_code)} yet, so there "
            f"is no running total to draw. It starts the first time you "
            f"reject a claim in the Review Queue.")
else:
    chart_data = running.reset_index()
    chart_data.columns = ["decided_at", "amount"]
    st.altair_chart(
        alt.Chart(chart_data).mark_line(point=True).encode(
            x=alt.X("decided_at:T", title="Decision date"),
            y=alt.Y("amount:Q",
                    title=f"Cumulative leakage prevented ({currency_label(running_total_code)})"),
            tooltip=[alt.Tooltip("decided_at:T", title="Decided on"),
                     alt.Tooltip("amount:Q", title="Cumulative total",
                                 format=",.2f")],
        ),
        use_container_width=True,
    )
    st.caption(
        f"Cumulative value of rejected claims in {currency_label(running_total_code)}. "
        f"Each point is the running total as of the date a claim was "
        f"rejected — the x-axis is time, the y-axis is money not paid out so "
        f"far."
    )

st.subheader("Spend by category")
category_code = st.selectbox(
    "Currency", currencies, format_func=currency_label, key="currency_category",
    index=currencies.index(default_currency(currencies)))
by_currency = df[df["currency"].astype("string").fillna("").str.strip().str.upper()
                 == category_code]
# Categories are normalised first — the sheet holds both `Travel` from n8n and
# `travel` from the audit engine, and grouping the raw column would split one
# category across two bars.
by_category = (by_currency.assign(category=by_currency["category"].map(normalise_category))
               .groupby("category")["total"].sum()
               .sort_values(ascending=False))
if by_category.empty:
    st.info(f"No categorised spend yet in {currency_label(category_code)}.")
else:
    chart_data = by_category.reset_index()
    chart_data.columns = ["category", "total"]
    st.altair_chart(
        alt.Chart(chart_data).mark_bar().encode(
            x=alt.X("category:N", title="Category", sort="-y",
                    axis=alt.Axis(labelAngle=-20)),
            y=alt.Y("total:Q", title=f"Total spend ({currency_label(category_code)})"),
            tooltip=[alt.Tooltip("category:N", title="Category"),
                     alt.Tooltip("total:Q", title="Total spend", format=",.2f")],
        ),
        use_container_width=True,
    )
    st.caption(
        f"All claims in {currency_label(category_code)}, whatever their outcome.")

if currencies:
    forecast_code = st.selectbox(
        "Currency", currencies, format_func=currency_label, key="currency_forecast",
        index=currencies.index(default_currency(currencies)))
    render_forecast(df, forecast_code)
else:
    render_forecast(df, UNKNOWN_CURRENCY)
