import pandas as pd
import streamlit as st

from dashboard.data import load_mock_receipts

st.title("Expense Browser")

df = load_mock_receipts()

col1, col2, col3 = st.columns(3)
date_range = col1.date_input(
    "Date range", value=(df["date"].min(), df["date"].max())
)
categories = col2.multiselect(
    "Category", options=sorted(df["category"].unique()), default=None
)
submitters = col3.multiselect(
    "Submitter", options=sorted(df["submitter"].unique()), default=None
)
min_amount, max_amount = st.slider(
    "Amount range",
    float(df["total"].min()), float(df["total"].max()),
    (float(df["total"].min()), float(df["total"].max())),
)

filtered = df[
    (df["date"] >= pd.Timestamp(date_range[0]))
    & (df["date"] <= pd.Timestamp(date_range[1]))
    & (df["total"] >= min_amount)
    & (df["total"] <= max_amount)
]
if categories:
    filtered = filtered[filtered["category"].isin(categories)]
if submitters:
    filtered = filtered[filtered["submitter"].isin(submitters)]

st.dataframe(
    filtered[["receipt_id", "date", "merchant", "category", "submitter", "total", "verdict", "status"]],
    use_container_width=True,
)
