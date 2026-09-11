import pandas as pd
import streamlit as st

from api.policy import normalise_category
from dashboard.data import load_expenses

st.title("Expense Browser")

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

# A receipt whose date could not be read is held aside and reported, not
# dropped from the filter silently.
dated = df[df["date"].notna()]
undated = df[df["date"].isna()]

col1, col2, col3, col4 = st.columns(4)
if dated.empty:
    date_range = ()
    col1.warning("No readable dates")
else:
    date_range = col1.date_input(
        "Date range", value=(dated["date"].min(), dated["date"].max())
    )
# Normalised first — the sheet holds both `Travel` from n8n and `travel` from
# the audit engine, and filtering on the raw column would miss half of one
# category's rows depending which spelling was picked.
categories = col2.multiselect(
    "Category", options=sorted(df["category"].map(normalise_category).dropna().unique()),
    default=None
)
submitters = col3.multiselect(
    "Submitter", options=sorted(df["submitter"].dropna().unique()), default=None
)
currencies = col4.multiselect(
    "Currency", options=sorted(df["currency"].dropna().unique()), default=None
)

amounts = df["total"].dropna()
if amounts.empty or amounts.min() == amounts.max():
    min_amount, max_amount = float("-inf"), float("inf")
else:
    min_amount, max_amount = st.slider(
        "Amount range",
        float(amounts.min()), float(amounts.max()),
        (float(amounts.min()), float(amounts.max())),
    )

filtered = df[(df["total"] >= min_amount) & (df["total"] <= max_amount)]

# st.date_input hands back a 1-tuple mid-selection, so both ends must be
# present before the range is applied.
if len(date_range) == 2:
    filtered = filtered[filtered["date"].notna()
                        & (filtered["date"] >= pd.Timestamp(date_range[0]))
                        & (filtered["date"] <= pd.Timestamp(date_range[1]))]
if categories:
    filtered = filtered[filtered["category"].map(normalise_category).isin(categories)]
if submitters:
    filtered = filtered[filtered["submitter"].isin(submitters)]
if currencies:
    filtered = filtered[filtered["currency"].isin(currencies)]

st.caption(f"Showing {len(filtered)} of {len(df)} receipts.")

st.dataframe(
    filtered[["receipt_id", "date", "merchant", "category", "submitter", "total", "currency", "verdict", "status"]],
    use_container_width=True,
)

if not undated.empty:
    with st.expander(f"{len(undated)} receipt(s) with an unreadable date "
                     f"— excluded from the date filter"):
        st.caption(
            "The date on these could not be parsed, so they cannot be placed on "
            "a timeline. Fix `receipt_date` in the Receipts tab to bring them in."
        )
        st.dataframe(
            undated[["receipt_id", "receipt_date", "merchant", "category",
                     "submitter", "total", "verdict", "status"]],
            use_container_width=True,
        )
