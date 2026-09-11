import streamlit as st

st.set_page_config(page_title="CFO Eyes Dashboard", layout="wide")

st.title("CFO Eyes Dashboard")
st.write(
    "Use the sidebar to navigate:\n\n"
    "- **Spend Overview** — what was claimed, what is at risk, what was "
    "prevented, spend velocity, and a next-month travel forecast (with two "
    "further months shown for context)\n"
    "- **Review Queue** — high-risk claims awaiting your decision\n"
    "- **Expense Browser** — every claim, filterable\n"
    "- **Policy Health** — how compliance is trending and which handbook rules "
    "are being broken\n"
    "- **Patterns of Concern** — claims that look like the same claim, filed "
    "more than once or split across people\n\n"
    "Reads and writes the shared Google Sheet (Receipts / Cluster Reviews "
    "tabs) — see `ticket_work/epic_3_tickets.md` for the one-time credentials "
    "setup."
)
