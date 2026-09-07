import streamlit as st

st.set_page_config(page_title="CFO Eyes Dashboard", layout="wide")

st.title("CFO Eyes Dashboard")
st.write(
    "Use the sidebar to navigate: **Spend Overview**, **Review Queue**, "
    "**Expense Browser**. Currently running on mock data from "
    "`data/annotations.xml` — swap for live DB queries once C1/C6 land."
)
