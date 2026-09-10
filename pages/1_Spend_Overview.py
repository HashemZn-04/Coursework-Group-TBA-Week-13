import streamlit as st

from api.summary import format_money
from dashboard.data import load_expenses
from dashboard.forecast_view import render_forecast
from dashboard.spend import (UNKNOWN_CURRENCY, prevented_running_total,
                             spend_over_time, spend_summary)

st.title("Spend Overview")

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

summary = spend_summary(df)
currencies = summary.currencies


def _label(code: str) -> str:
    return "Currency not recorded" if code == UNKNOWN_CURRENCY else code


# Totals are shown per currency and never added together. The sheet holds USD
# sample receipts while every handbook limit is GBP, and nothing in this
# pipeline converts between them — Handbook 12.2 wants the rate on the date the
# expense was incurred, and no FX source is wired in.
if len(currencies) > 1:
    st.caption(
        "Totals are shown per currency. Nothing here converts between them "
        "(Handbook 12.2 wants the rate on the transaction date; no exchange-rate "
        "source is wired in), so weigh the rate and local purchasing power "
        "yourself before comparing the rows."
    )

for code in currencies:
    row = summary.totals.loc[code]
    if len(currencies) > 1 or code == UNKNOWN_CURRENCY:
        st.subheader(_label(code))

    claimed, approved, at_risk, prevented = st.columns(4)
    claimed.metric("Claimed", format_money(row["claimed"], code),
                   help="Everything submitted, whatever happened to it next — "
                        "including claims still awaiting a decision and claims "
                        "the pipeline never processed.")
    claimed.caption(f"{int(row['claimed_count'])} claims")

    approved.metric("Approved", format_money(row["approved"], code),
                    help="Claims with a standing approval — yours, or the "
                         "engine's automatic approval of a low-risk claim. "
                         "This money is payable.")
    approved.caption(f"{int(row['approved_count'])} claims")

    at_risk.metric("At risk · awaiting your decision",
                   format_money(row["at_risk"], code),
                   help="High-risk claims with no decision recorded. This is "
                        "money at risk, not money saved — nothing is prevented "
                        "until you reject it.")
    at_risk.caption(f"{int(row['at_risk_count'])} claims")

    prevented.metric("Leakage prevented", format_money(row["prevented"], code),
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

# Every receipt the pipeline processes ends up either auto-approved or queued.
# A receipt holding neither verdict did not complete the pipeline, so this is a
# processing failure, not a third category. It is inside Claimed — somebody did
# claim that money — and in none of the outcome tiles, because nothing has
# assessed it.
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

# One currency per chart — an axis cannot carry two units. The busiest currency
# is the one charted; the tiles above already cover them all.
chart_currency = currencies[0] if currencies else UNKNOWN_CURRENCY

st.subheader("Spend velocity")
timeline = spend_over_time(df, chart_currency)
if timeline.empty:
    st.info("No receipt in this currency has a readable date, so there is "
            "nothing to plot over time.")
else:
    st.bar_chart(timeline["spend"])
    grain = {"D": "day", "W": "week", "MS": "month", "QS": "quarter",
             "YS": "year"}
    freq = timeline.index.freqstr or ""
    st.caption(
        f"Spend per {grain.get(freq.split('-')[0], 'period')}, in "
        f"{_label(chart_currency)} — {int(timeline['receipts'].sum())} claims "
        f"across {len(timeline)} periods. Periods with no claims are drawn as "
        f"zero, because a quiet month is a fact about velocity."
    )
    undated = int(df["date"].isna().sum())
    if undated:
        st.caption(f"{undated} receipt(s) omitted — no readable date.")

st.subheader("Leakage prevented, running total")
running = prevented_running_total(df, chart_currency)
if running.empty:
    st.info("Nothing rejected yet in this currency, so there is no running "
            "total to draw. It starts the first time you reject a claim.")
else:
    st.line_chart(running)
    st.caption(
        f"Cumulative value of rejected claims in {_label(chart_currency)}, "
        f"plotted on the date the claim was rejected."
    )

st.subheader("Spend by category")
by_currency = df[df["currency"].astype("string").fillna("").str.strip().str.upper()
                 == chart_currency]
by_category = by_currency.groupby(
    "category")["total"].sum().sort_values(ascending=False)
if by_category.empty:
    st.info("No categorised spend in this currency yet.")
else:
    st.bar_chart(by_category)
    st.caption(
        f"All claims in {_label(chart_currency)}, whatever their outcome.")

render_forecast(df, chart_currency)
