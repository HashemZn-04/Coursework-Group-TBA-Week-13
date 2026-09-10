import pandas as pd
import streamlit as st

from api.policy import VERDICT_HIGH
from api.summary import format_money
from dashboard.data import load_expenses, update_decision

st.title("Review Queue")
st.caption(
    "Everything the audit engine could not clear on its own, newest first. "
    "Low-risk receipts are approved automatically and never appear here, and a "
    "receipt leaves this queue once you have decided it. "
    "The summary under each receipt is the one the submitter also received in "
    "Slack — same text, same source (the receipt's `verdict_reason` column)."
)

df = load_expenses()

# A receipt leaves the queue the moment its status stops being pending_review,
# so filtering on verdict plus status is enough — no separate decision history
# to reconcile against.
queue = df[(df["verdict"] == VERDICT_HIGH)
           & (df["status"].astype("string").str.strip().str.lower()
              == "pending_review")] if not df.empty else df

# A receipt with no verdict is not a quieter kind of queue item — it never went
# through the pipeline at all. It does not belong in the list below (nothing
# assessed it as high risk), but it must not be invisible either: it is an
# expense sitting in the system that nobody and nothing has acted on.
unprocessed = df[df["verdict"].isna()] if not df.empty else df
if not unprocessed.empty:
    st.error(
        f"**{len(unprocessed)} receipt(s) never completed the audit pipeline.** "
        f"They were neither auto-approved nor queued, which should not be "
        f"possible — the pipeline did not run for them. They are not listed "
        f"below because nothing has assessed them, but they still need "
        f"resolving."
    )
    with st.expander(f"Show the {len(unprocessed)} unprocessed receipt(s)"):
        st.dataframe(
            unprocessed[["receipt_id", "date", "merchant", "category",
                         "submitter", "total", "status"]],
            use_container_width=True,
        )

if queue.empty:
    st.info("No receipts pending review.")
    st.stop()

# Newest first. Everything here is the same tier now, so date is the only
# ordering that means anything — and Amara is the sole approver, so this queue
# is the bottleneck the whole workflow exists to shorten.
queue = queue.sort_values("date", ascending=False)

st.write(f"**{len(queue)}** awaiting your decision.")

for _, row in queue.iterrows():
    with st.container(border=True):
        st.write(":red[High risk] — needs your decision")
        st.subheader(
            f"{row['merchant']} — {format_money(row['total'], row.get('currency'))}")

        date = row["date"]
        st.caption(
            f"{row['category']} · submitted by {row['submitter']} · "
            f"dated {date:%Y-%m-%d}" if pd.notna(date)
            else f"{row['category']} · submitted by {row['submitter']}"
        )

        reason = row.get("verdict_reason")
        if isinstance(reason, str) and reason.strip():
            st.write(reason)
        else:
            st.warning("No reasoning was stored against this verdict.")

        if pd.isna(row["receipt_id"]):
            st.error(
                "This receipt has no usable `receipt_id`, so a decision cannot "
                "be recorded against it. Fix the ID in the Receipts tab first."
            )
            continue

        receipt_id = int(row["receipt_id"])
        approve, reject = st.columns(2)
        if approve.button("Approve", key=f"approve-{receipt_id}",
                          use_container_width=True):
            update_decision(receipt_id, "approved")
            st.rerun()
        if reject.button("Reject", key=f"reject-{receipt_id}",
                         use_container_width=True):
            update_decision(receipt_id, "rejected")
            st.rerun()
