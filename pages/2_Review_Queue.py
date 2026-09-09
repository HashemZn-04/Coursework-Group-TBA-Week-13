import streamlit as st

from dashboard.data import load_expenses, record_decision

st.title("Review Queue")
st.caption("Verdicts here come from the Verdicts tab of the shared Google Sheet.")

df = load_expenses()
queue = df[df["verdict"].isin(["flagged", "high_risk"])] if not df.empty else df

if queue.empty:
    st.info("No receipts pending review.")

for _, row in queue.iterrows():
    with st.container(border=True):
        st.write(
            f"**{row['merchant']}** — ${row['total']:,.2f} "
            f"({row['category']}) submitted by {row['submitter']}"
        )
        st.write(f"Verdict: `{row['verdict']}`")
        c1, c2 = st.columns(2)
        if c1.button("Approve", key=f"approve-{row['receipt_id']}"):
            record_decision(int(row["receipt_id"]), "approved")
            st.rerun()
        if c2.button("Reject", key=f"reject-{row['receipt_id']}"):
            record_decision(int(row["receipt_id"]), "rejected")
            st.rerun()
