import streamlit as st

from dashboard.data import load_mock_receipts

st.title("Spend Overview")

df = load_mock_receipts()

col1, col2, col3 = st.columns(3)
col1.metric("Total Spend", f"${df['total'].sum():,.2f}")
col2.metric("Receipts", len(df))
leakage = df.loc[df["verdict"].isin(["flagged", "high_risk"]), "total"].sum()
col3.metric("Flagged Amount (potential leakage)", f"${leakage:,.2f}")

st.subheader("Spend over time")
st.line_chart(df.set_index("date")["total"])

st.subheader("Spend by category")
st.bar_chart(df.groupby("category")["total"].sum())
