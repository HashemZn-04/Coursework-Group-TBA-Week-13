import streamlit as st

from dashboard.data import load_mock_receipts

st.title("Review Queue")
st.caption("Verdicts here are a placeholder rule, not C3's real Governance Prompt.")

df = load_mock_receipts()
queue = df[df["verdict"].isin(["flagged", "high_risk"])]

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
        # No D2 API yet — buttons are UI-only placeholders for now.
        c1.button("Approve", key=f"approve-{row['receipt_id']}")
        c2.button("Reject", key=f"reject-{row['receipt_id']}")
