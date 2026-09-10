import streamlit as st

from api.clusters import (DUPLICATE, IMMATERIAL, REVIEW, SYNDICATED,
                          find_patterns, pattern_identity)
from api.summary import format_money
from dashboard.data import (load_cluster_reviews, load_expenses,
                            record_cluster_review)

st.title("Patterns of Concern")
st.caption(
    "Handbook 10.2 asks Finance to watch for \"clustering of similar claims "
    "across multiple employees on the same date\", and 9.2 says the aggregation "
    "rule exists to deter split-receipting. Nobody has time to do that by hand — "
    "Amara: \"it depends on one of us getting suspicious about something and "
    "then looking back through, but there's no good trigger for that\". This is "
    "the trigger. It is a prompt to look, never a finding of wrongdoing."
)

df = load_expenses()

if df.empty:
    st.info("No receipts in the sheet yet. Submit a receipt via Slack, or add a test row to the "
            "Receipts tab: https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE")
    st.stop()

patterns = find_patterns(df)
reviews = load_cluster_reviews()
reviewed = set(reviews["receipt_ids"].astype(
    "string").fillna("")) if not reviews.empty else set()

if not patterns:
    st.success(
        "No group of claims in the sheet looks like the same claim submitted "
        "more than once. Claims are only compared against others from the same "
        "merchant and currency, within a few days and a few percent of each "
        "other — so this staying empty is the ordinary result, not a failure."
    )
    st.stop()

to_review = [p for p in patterns if p.severity == REVIEW]
immaterial = [p for p in patterns if p.severity == IMMATERIAL]
outstanding = [p for p in to_review if pattern_identity(
    p.receipt_ids) not in reviewed]

st.write(f"**{len(outstanding)}** pattern(s) worth a look; "
         f"{len(to_review) - len(outstanding)} already reviewed.")

PATTERN_LABELS = {
    SYNDICATED: (":red[Across several people]",
                 "Several employees each claimed something that looks like part "
                 "of one shared expense — the split-receipting shape Handbook "
                 "9.2 exists to deter."),
    DUPLICATE: (":orange[Same person, more than once]",
                "One person filed claims that look like the same claim more "
                "than once."),
}


def _render(pattern, already_reviewed: bool):
    identity = pattern_identity(pattern.receipt_ids)
    label, explanation = PATTERN_LABELS[pattern.pattern]
    with st.container(border=True):
        st.write(label + (" · reviewed" if already_reviewed else ""))
        st.subheader(f"{pattern.merchant} — "
                     f"{format_money(pattern.total, pattern.currency)} "
                     f"across {pattern.receipts} claims")
        st.caption(explanation)
        st.write(pattern.basis)

        if pattern.exact_repeats:
            st.warning(
                "Identical claims from the same person: "
                + "; ".join(f"{who} filed the same claim {n} times"
                            for who, n in pattern.exact_repeats.items())
                + "."
            )

        members = df[df["receipt_id"].isin(list(pattern.receipt_ids))]
        st.dataframe(
            members[["receipt_id", "date", "merchant", "category", "submitter",
                     "total", "currency", "verdict", "status"]],
            use_container_width=True, hide_index=True,
        )

        if already_reviewed:
            st.caption(
                "You have marked this exact set of claims as reviewed. If "
                "another matching claim arrives the group will reappear here, "
                "because it would be a different set."
            )
            return

        note = st.text_input(
            "Note (optional — recorded against the review)",
            key=f"pattern-note-{identity}",
            placeholder="e.g. team offsite, checked with the practice lead",
        )
        if st.button("Mark reviewed", key=f"pattern-{identity}",
                     use_container_width=True):
            record_cluster_review(pattern.pattern, pattern.merchant,
                                  pattern.receipt_ids, notes=note)
            st.rerun()


for pattern in to_review:
    _render(pattern, pattern_identity(pattern.receipt_ids) in reviewed)

if immaterial:
    with st.expander(f"{len(immaterial)} group(s) below the materiality floor"):
        st.caption(
            "These claims group together but nothing about them is worth your "
            "time: every claim is under the itemised-receipt threshold "
            "(Handbook 8.1), the group total is under the approval threshold "
            "(9.1), they all fall on one date, and nobody filed the same claim "
            "twice. Two colleagues buying lunch at the same place on the same "
            "day looks exactly like this. They are listed rather than hidden so "
            "the filter can be checked."
        )
        for pattern in immaterial:
            st.write(f"- **{pattern.merchant}** · "
                     f"{format_money(pattern.total, pattern.currency)} across "
                     f"{pattern.receipts} claims from "
                     f"{len(pattern.submitters)} submitter(s) · "
                     f"{pattern.basis}")

st.subheader("What this can and cannot see")
st.markdown(
    """
- **This is a prompt to look, not a finding.** Handbook 10.2 is explicit that
  "the presence of any such pattern does not, on its own, establish misconduct".
  Marking a group reviewed records that you looked; it approves nothing. Money
  still moves one receipt at a time through the Review Queue.
- **Only claims from the same merchant and currency are ever compared**, within
  a few days and a few percent of each other. A split purchase whose halves came
  from different merchants is invisible here — that is what the governance
  prompt's split-receipting instruction is for.
- **A merchant name that reduces to nothing, or to one short word, matches
  nothing.** Otherwise every unreadable receipt would group with every other
  unreadable receipt, which is the fastest way to make a page like this
  worthless.
- **Thresholds are GBP.** Nothing converts (Handbook 12.2), and any group in
  another currency says so on its own card.
- **A review is recorded against the exact set of claims you saw.** If the group
  grows, it comes back — you cleared a different set.
"""
)
