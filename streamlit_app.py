import streamlit as st

st.set_page_config(page_title="CFO Eyes Dashboard", layout="wide")

st.title("CFO Eyes Dashboard")
st.write(
    "Use the sidebar to navigate: **Spend Overview**, **Review Queue**, "
    "**Expense Browser**. Reads and writes the shared Google Sheet "
    "(Receipts / Verdicts / Decisions tabs) — see "
    "`ticket_work/epic_3_tickets.md` for the one-time credentials setup."
)
