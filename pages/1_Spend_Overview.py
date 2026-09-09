import streamlit as st

from dashboard.data import load_expenses

st.title("Spend Overview")

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Total Spend", f"${df['total'].sum():,.2f}")
col2.metric("Receipts", len(df))
leakage = df.loc[df["verdict"].isin(["flagged", "high_risk"]), "total"].sum()
col3.metric("Flagged Amount (potential leakage)", f"${leakage:,.2f}")

st.subheader("Spend over time")
st.line_chart(df.set_index("date")["total"])

st.subheader("Spend by category")
st.bar_chart(df.groupby("category")["total"].sum())
