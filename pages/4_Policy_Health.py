import pandas as pd
import streamlit as st

from api.policy import normalise_category
from dashboard.data import load_expenses
from dashboard.policy_health import (CLEARED, MIN_RATE_BASE, NEEDS_REVIEW,
                                     NEVER_ASSESSED, STATE_LABELS, STATES,
                                     UNRECOGNISED, breakdown, clearance_rate,
                                     compliance_trend,
                                     repriced_within_todays_money,
                                     rule_breaches, trend_is_sparse,
                                     verdict_state)

st.title("Policy Health")
st.caption(
    "Two questions, from two sources. **Is the pipeline clearing claims, and is "
    "that changing?** comes from the verdicts it has stored. **Which handbook "
    "rules are actually being broken?** is re-checked here against the receipts "
    "themselves, so it works on claims the pipeline never finished."
)

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

states = df["verdict"].map(verdict_state)
counts = {state: int((states == state).sum()) for state in STATES}
assessed = counts[CLEARED] + counts[NEEDS_REVIEW]
rate = clearance_rate(counts[CLEARED], counts[NEEDS_REVIEW])


def rate_text(value: float, base: int) -> str:
    return "—" if pd.isna(value) else f"{value:.0%}"


assessed_tile, cleared_tile, queue_tile, misc_tile = st.columns(4)

assessed_tile.metric("Assessed", f"{assessed} of {len(df)}",
                     help="Receipts the audit pipeline reached a verdict on. "
                          "The rest are not compliant and not flagged — nothing "
                          "has looked at them.")
assessed_tile.caption(f"{assessed / len(df):.0%} of all receipts")

cleared_tile.metric("Cleared without a human", rate_text(rate, assessed),
                    help="Share of assessed receipts the engine approved on its "
                         "own. Unassessed receipts are in neither the top nor "
                         "the bottom of this fraction.")
cleared_tile.caption(
    f"{counts[CLEARED]} of {assessed} assessed"
    + ("" if assessed >= MIN_RATE_BASE
       else f" — too few to state a rate (need {MIN_RATE_BASE})"))

queue_tile.metric("Needs a decision", counts[NEEDS_REVIEW],
                  help="Receipts the engine could not clear. These are the "
                       "Review Queue.")
queue_tile.caption("in the Review Queue")

misc = int((df["category"].map(normalise_category) == "MISCELLANEOUS").sum())
misc_tile.metric("Coded Miscellaneous", f"{misc} of {len(df)}",
                 help="Amara's own headline complaint: Miscellaneous \"used to "
                      "be this, like, our most common category, and it should "
                      "be our rarest by miles\". Categorisation happens at "
                      "intake, so this needs no verdict.")
misc_tile.caption(f"{misc / len(df):.2%} of all receipts")

if counts[NEVER_ASSESSED]:
    st.error(
        f"**{counts[NEVER_ASSESSED]} of {len(df)} receipts never completed the "
        f"audit pipeline.** Every receipt should end up either auto-approved or "
        f"in the review queue — these are in neither, which means the pipeline "
        f"did not run for them. They are drawn on the chart below as their own "
        f"state and are excluded from every rate on this page, top and bottom: "
        f"an unassessed claim is not a compliant one."
    )

if counts[UNRECOGNISED]:
    st.warning(
        f"{counts[UNRECOGNISED]} receipt(s) carry a verdict that is neither "
        f"`low_risk` nor `high_risk`. They are counted separately so the chart "
        f"still adds up; fix the value in the Receipts tab."
    )

st.subheader("Policy health over time")

trend = compliance_trend(df)
if trend.empty:
    st.info("No receipt has a readable date, so there is nothing to trend.")
else:
    if trend_is_sparse(trend):
        st.warning(
            f"Only {len(trend)} calendar month(s) contain receipts"
            + (f", spanning {trend.index[0]} to {trend.index[-1]}"
               if len(trend) > 1 else "")
            + ". Read this as a composition, not a trend."
        )
    chart = trend[list(STATES)].rename(columns=STATE_LABELS)
    chart = chart.loc[:, chart.sum() > 0]
    st.bar_chart(chart)
    st.caption(
        "Receipt counts per calendar month, by what the pipeline decided. "
        "Counts rather than a 100%-stack on purpose: a normalised stack makes a "
        "month holding one receipt look exactly as substantial as a month "
        "holding two hundred. Bucketed on the date of the expense, not on when "
        "the engine got round to judging it — otherwise the day the pipeline is "
        "fixed and the backlog is audited would draw as a compliance event."
    )

    monthly = trend[["receipts", "assessed", CLEARED, NEEDS_REVIEW,
                     NEVER_ASSESSED, "clearance_rate"]].rename(columns={
                         "receipts": "receipts", "assessed": "assessed",
                         CLEARED: "auto-approved", NEEDS_REVIEW: "needs review",
                         NEVER_ASSESSED: "never assessed",
                         "clearance_rate": "clearance rate"})
    st.dataframe(monthly.style.format({"clearance rate": "{:.0%}"},
                                      na_rep="—"),
                 use_container_width=True)
    st.caption(
        f"The clearance rate is blank where fewer than {MIN_RATE_BASE} receipts "
        f"in the month were assessed — a percentage over a base of one or two "
        f"is noise, not a trend."
    )

st.subheader("Most-broken rules")

breaches = rule_breaches(df)
breached = breaches[breaches["breaches"] > 0]
if breached.empty:
    st.info("No receipt breaks any of the rules re-checked here. The checks "
            "that could be run are listed below with the number of receipts "
            "each was evaluated against.")
else:
    st.bar_chart(breached.set_index("label")["breaches"], horizontal=True)
    st.caption(
        "Number of receipts breaking each rule. A receipt can break several and "
        "is counted once under each, so these do not add up to the receipt "
        "count. Ranked by count rather than by rate: ranking by rate would put "
        "whichever rule was evaluated once at the top every time."
    )

st.dataframe(
    breaches.assign(
        enforced=breaches["enforced"].map(
            {True: "yes", False: "not yet"}))[
        ["label", "breaches", "evaluated", "enforced"]].rename(columns={
            "label": "rule", "breaches": "receipts breaking it",
            "evaluated": "receipts it could be checked against",
            "enforced": "enforced by the pipeline"}),
    use_container_width=True, hide_index=True,
)
st.caption(
    "Each rule carries its own base, because most of them cannot be evaluated "
    "against every receipt — seven of the twelve handbook categories set no "
    "numeric ceiling at all, and the one-month check needs both a readable "
    "expense date and a readable submission time. The two rules marked *not "
    "yet* are in the handbook and in nothing else: the live pipeline does not "
    "check them, which is a gap for the team rather than a fact about "
    "employees."
)

good_deals, priced_base = repriced_within_todays_money(df)
if priced_base:
    st.info(
        f"**Policy decay: {good_deals} of {priced_base}** claims in a category "
        f"the handbook actually caps were over the written figure but inside "
        f"the same figure restated in today's money. Those are stale rules, not "
        f"overspending — which is the difference between \"our people got "
        f"worse\" and \"our rules got older\"."
    )
else:
    st.caption(
        "No claim yet falls in a category the handbook sets a number for, so "
        "there is nothing to re-price. Travel, accommodation, training, office "
        "supplies, postage and miscellaneous have no numeric ceiling — they are "
        "governed by the approval thresholds instead."
    )

st.subheader("By category")
st.dataframe(
    breakdown(df, "category").style.format(
        {"review_rate": "{:.0%}"}, na_rep="—"),
    use_container_width=True)
st.caption(
    "Categories are normalised first — the sheet holds both `Travel` from n8n "
    "and `travel` from the audit engine, and grouping the raw column would "
    "split one category across two rows. A category that looks clean only "
    "because nothing in it was ever audited shows that in the *never assessed* "
    "column."
)

with st.expander("By submitter"):
    st.caption(
        "Amara: \"If someone is consistently going over the edge, that is part "
        "of the risk category\" — and, on the current spreadsheet, \"I can't "
        "say, like, this person always orders twice as much\". This is the "
        "smallest version of that."
    )
    st.dataframe(
        breakdown(df, "submitter").style.format({"review_rate": "{:.0%}"},
                                                na_rep="—"),
        use_container_width=True)
