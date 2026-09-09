import pandas as pd
import streamlit as st

from api.summary import format_money
from dashboard.data import load_expenses, record_decision

st.title("Review Queue")
st.caption(
    "Everything the audit engine could not clear on its own, newest first. "
    "The summary under each receipt is the one the submitter also received in "
    "Slack — same text, same source (the Verdicts tab's `reason` column)."
)

df = load_expenses()
queue = df[df["verdict"].isin(["flagged", "high_risk"])] if not df.empty else df

if queue.empty:
    st.info("No receipts pending review.")
    st.stop()

# High risk needs Amara's decision; flagged is waiting on the employee. Show the
# ones that need her first — she is the only approver, so her queue is the
# bottleneck the whole workflow is trying to shorten.
order = {"high_risk": 0, "flagged": 1}
queue = queue.assign(_rank=queue["verdict"].map(order)).sort_values(
    ["_rank", "date"], ascending=[True, False])

high_risk = int((queue["verdict"] == "high_risk").sum())
st.write(f"**{len(queue)}** awaiting review — {high_risk} high risk, "
         f"{len(queue) - high_risk} flagged for explanation.")

LABELS = {"high_risk": ":red[High risk] — needs your decision",
          "flagged": ":orange[Flagged] — needs an employee explanation"}

for _, row in queue.iterrows():
    with st.container(border=True):
        st.write(LABELS.get(row["verdict"], row["verdict"]))
        st.subheader(f"{row['merchant']} — {format_money(row['total'], row.get('currency'))}")

        date = row["date"]
        st.caption(
            f"{row['category']} · submitted by {row['submitter']} · "
            f"dated {date:%Y-%m-%d}" if pd.notna(date)
            else f"{row['category']} · submitted by {row['submitter']}"
        )

        reason = row.get("reason")
        if isinstance(reason, str) and reason.strip():
            st.write(reason)
        else:
            st.warning(
                "No reasoning was stored against this verdict. The Verdicts tab "
                "row is missing or empty — see the C3 punch list in "
                "`ticket_work/epic_3_tickets.md`."
            )

        if pd.isna(row["receipt_id"]):
            st.error(
                "This receipt has no usable `receipt_id`, so a decision cannot "
                "be recorded against it. Fix the ID in the Receipts tab first."
            )
            continue

        receipt_id = int(row["receipt_id"])
        note = st.text_input(
            "Note (optional — recorded in the audit trail)",
            key=f"note-{receipt_id}", placeholder="e.g. last-minute booking, confirmed with the client team",
        )
        approve, reject = st.columns(2)
        if approve.button("Approve", key=f"approve-{receipt_id}",
                          use_container_width=True):
            record_decision(receipt_id, "approved", notes=note)
            st.rerun()
        if reject.button("Reject", key=f"reject-{receipt_id}",
                         use_container_width=True):
            record_decision(receipt_id, "rejected", notes=note)
            st.rerun()
