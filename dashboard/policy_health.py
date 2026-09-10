"""
E3 — policy health trends (MCP ticket "Build policy health trend view").

The brief names three headline dashboard outputs: "real-time spend velocity,
identified 'Leakage' (money saved), and **policy health trends**". The first two
had pages. This is the third, and Amara's own framing of what it is for is
narrow and useful: "If someone is consistently going over the edge, that is part
of the risk category [...] we definitely want to" analyse the trends, and — on
her most-repeated complaint — Miscellaneous "used to be this, like, our most
common category, and it should be our rarest by miles".

Two questions, answered from two different sources, and the page keeps them
apart because they can be true at different times:

1. **Is the pipeline clearing claims, and is that changing?** Answered from the
   `verdict` column on each receipt. Thin today — one verdict against eight
   receipts — and it thickens as more receipts are processed.
2. **Which handbook rules are actually being broken?** Answered by re-running
   the deterministic rules against the receipts themselves. That needs no
   verdict, so it works on every row in the sheet right now.

**Why the rules are recomputed rather than read back.** The flag codes that the
engine produces (`CFO_APPROVAL_THRESHOLD` and friends, listed in
`api.summary.FLAG_DESCRIPTIONS`) exist upstream and are thrown away at persist
time: the Receipts row stores `verdict`, `verdict_reason` and `decided_at`, and
the `verdict_reason` written on the live n8n path is the governance prompt's
free-text sentence, which contains no codes at all. Recovering them by matching
prose would give a chart whose completeness depended on which code path wrote
the row — full for rows written by `/api/audit`, empty for rows written by n8n
— with nothing on screen saying so. Recomputing is reproducible, explains
itself, and covers receipts the pipeline never finished.

**What recomputing costs, stated rather than buried.** It sees the deterministic
layer and C4 and nothing else: the AI's contextual `risk_factors` are not
recoverable from the sheet, so this under-counts. It also includes two handbook
rules the pipeline does not enforce at all (2.2's Miscellaneous justification
and 8.1's itemised-receipt requirement), which are marked as such — the gap
between what the handbook says and what the pipeline checks is itself worth
seeing. And the one-month cutoff uses `created_at` (when the row reached the
sheet) as a stand-in for submission time, where n8n uses the Slack message
timestamp, so a hand-added or backfilled row reads as a late submission.

Everything here is a pure function over frames the loaders have already cached.
"""

import pandas as pd

from api.audit import contextual_validation
from api.policy import (MISC_JUSTIFICATION_THRESHOLD,
                        RECEIPT_REQUIRED_THRESHOLD, VERDICT_HIGH, VERDICT_LOW,
                        limit_for, normalise_category)
from api.summary import FLAG_DESCRIPTIONS, VERDICT_HEADLINES

#: The four states a receipt can be in on this page. `never_assessed` is not a
#: verdict and never becomes one — `api.policy.normalise_verdict` is explicit
#: that a missing verdict means the pipeline did not finish, which is a
#: processing failure to fix, not a classification. It is drawn, counted, and
#: kept out of the numerator *and* the denominator of every rate: folding
#: unassessed receipts into a compliance denominator would render a pipeline
#: outage as a compliance collapse — the wrong diagnosis and the wrong fix.
CLEARED = "cleared"
NEEDS_REVIEW = "needs_review"
NEVER_ASSESSED = "never_assessed"
UNRECOGNISED = "unrecognised"
STATES = (CLEARED, NEEDS_REVIEW, NEVER_ASSESSED, UNRECOGNISED)

#: Display names. The first two come from `api.summary` so that Slack, the
#: review queue and this chart cannot end up with three vocabularies for the
#: same two outcomes.
STATE_LABELS = {
    CLEARED: VERDICT_HEADLINES[VERDICT_LOW],
    NEEDS_REVIEW: VERDICT_HEADLINES[VERDICT_HIGH],
    NEVER_ASSESSED: "Never assessed",
    UNRECOGNISED: "Unrecognised verdict",
}

#: Below this many assessed receipts a percentage is not shown at all — the
#: count is, and the base beside it. **This number is ours, not Amara's**;
#: nothing in the handbook or the interview sets a materiality floor. It exists
#: so that "100% flagged" over a single receipt cannot read as a trend, which on
#: a sheet this size is the most likely way this page could mislead.
MIN_RATE_BASE = 5

#: Fewer populated months than this and the chart is a composition, not a trend.
#: Also ours. The gap rule beside it catches the live sheet's actual shape: two
#: populated months sixteen years apart, which is a real span and not a trend.
MIN_TREND_PERIODS = 3
MAX_TREND_GAP_MONTHS = 12

#: Rules the dashboard re-checks, in the order they are worth reading.
#:
#: `enforced` says whether the live pipeline checks this rule too. The first
#: four are in n8n's "Deterministic Policy Checks" and "Final Risk Assessment"
#: nodes or in C4, so a breach here should also have produced a flag upstream.
#: The last two are in the handbook and in nothing else — the pipeline does not
#: look for them, which is a gap for the team rather than a fact about
#: employees, and the page says so.
_HANDBOOK_LABELS = {
    "MISC_JUSTIFICATION_REQUIRED":
        f"coded to Miscellaneous at or above £{MISC_JUSTIFICATION_THRESHOLD:,.0f}, "
        "which needs a written justification (Handbook 2.2)",
    "ITEMISED_RECEIPT_REQUIRED":
        f"at or above £{RECEIPT_REQUIRED_THRESHOLD:,.0f} with no itemised lines "
        "captured, where policy requires an itemised receipt (Handbook 8.1)",
}


def rule_label(code: str) -> str:
    """The sentence a human reads for a rule code.

    `FLAG_DESCRIPTIONS` is the engine's own wording, reused verbatim so the
    dashboard and the Slack reply describe the same breach the same way.
    """
    return FLAG_DESCRIPTIONS.get(code) or _HANDBOOK_LABELS.get(code) or code


def verdict_state(verdict) -> str:
    """Which of the four states a stored verdict puts a receipt in."""
    if verdict is None or verdict is pd.NA:
        return NEVER_ASSESSED
    if isinstance(verdict, float) and pd.isna(verdict):
        return NEVER_ASSESSED
    value = str(verdict).strip()
    if not value:
        return NEVER_ASSESSED
    if value == VERDICT_LOW:
        return CLEARED
    if value == VERDICT_HIGH:
        return NEEDS_REVIEW
    return UNRECOGNISED


def clearance_rate(cleared: int, needs_review: int) -> float:
    """Share of *assessed* receipts the engine cleared on its own.

    NaN below `MIN_RATE_BASE`, so the caller shows the counts instead of a
    percentage nobody should act on.
    """
    assessed = cleared + needs_review
    if assessed < MIN_RATE_BASE:
        return float("nan")
    return cleared / assessed


def compliance_trend(expenses: pd.DataFrame) -> pd.DataFrame:
    """Receipt counts per state, per calendar month — the trend chart's data.

    Bucketed on **`receipt_date`** (when the money was spent), not on the
    verdict's `created_at` (when the engine got round to judging it). Three
    reasons: it is the question that was asked — how the firm's spending is
    behaving is a property of the expense, not of our pipeline; `created_at` is
    not stable under reprocessing, so the day C3's gap closes and seven backlog
    receipts are audited at once, a `created_at` trend would draw our deployment
    history as a compliance event; and Spend Overview already plots on the
    receipt date, so clocking the same receipt differently on two pages would
    make them disagree for no visible reason.

    Only months that actually contain a receipt appear. The live span is
    sixteen years with two populated months; reindexing across it would produce
    a chart that is 99% whitespace.

    Returns a frame indexed by `YYYY-MM` with one column per state, plus
    `receipts`, `assessed` and `clearance_rate` (NaN below the base floor).
    """
    columns = list(STATES) + ["receipts", "assessed", "clearance_rate"]
    empty = pd.DataFrame(columns=columns)
    empty.index.name = "month"
    if expenses is None or expenses.empty:
        return empty

    df = expenses[expenses["date"].notna()].copy()
    if df.empty:
        return empty

    df["state"] = df["verdict"].map(verdict_state)
    df["month"] = df["date"].dt.to_period("M").astype(str)

    counts = (df.groupby(["month", "state"]).size().unstack(fill_value=0)
              .reindex(columns=list(STATES), fill_value=0)
              .astype(int))
    counts.index.name = "month"
    counts = counts.sort_index()
    counts["receipts"] = counts[list(STATES)].sum(axis=1)
    counts["assessed"] = counts[CLEARED] + counts[NEEDS_REVIEW]
    counts["clearance_rate"] = [
        clearance_rate(int(row[CLEARED]), int(row[NEEDS_REVIEW]))
        for _, row in counts.iterrows()]
    return counts


def trend_is_sparse(trend: pd.DataFrame) -> bool:
    """True when the months on the chart are too few or too far apart to read
    as a trend, so the page can annotate the chart rather than hide it."""
    if trend.empty:
        return True
    if len(trend) < MIN_TREND_PERIODS:
        return True
    months = pd.PeriodIndex(trend.index, freq="M")
    if len(months) < 2:
        return True
    gaps = [(months[i + 1] - months[i]).n for i in range(len(months) - 1)]
    return max(gaps) > MAX_TREND_GAP_MONTHS


def _one_month_late(spent, submitted) -> bool | None:
    """Whether a claim missed the one-month window. None when unknowable.

    Amara, asked whether to keep the rule or tighten it: "a month feels good
    [...] they can do it inside a month, or they can deal with it." n8n
    implements it as one calendar month from the transaction date; the same
    shape is used here via a month offset rather than
    `SUBMISSION_WINDOW_DAYS`'s flat 30, so February does not get an extra
    day of grace that the live pipeline would not give it.
    """
    if pd.isna(spent) or pd.isna(submitted):
        return None
    return submitted > spent + pd.DateOffset(months=1)


def rule_breaches(expenses: pd.DataFrame) -> pd.DataFrame:
    """Per-rule counts: how many receipts break each handbook rule.

    One row per rule with the number that breached it, the number it could be
    evaluated against at all, and whether the live pipeline enforces it too.

    Each rule carries its **own** base. A single denominator across rules would
    be wrong for most of them: seven of the twelve categories have no numeric
    ceiling in the handbook, so a receipt coded Travel belongs in no
    category-limit denominator at all, and the cutoff check needs two readable
    dates before it can say anything.

    A receipt can break several rules and is counted once under each, so the
    column does not sum to the receipt count. That is by design; the page says
    so, because otherwise it reads as an arithmetic error.
    """
    columns = ["rule", "label", "breaches", "evaluated", "enforced"]
    if expenses is None or expenses.empty:
        return pd.DataFrame(columns=columns)

    checks = {code: {"breaches": 0, "evaluated": 0}
              for code in ("CFO_APPROVAL_THRESHOLD",
                           "EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF",
                           "INFLATION_ADJUSTED_LIMIT_EXCEEDED",
                           "OVER_CATEGORY_GUIDELINE",
                           "MISC_JUSTIFICATION_REQUIRED",
                           "ITEMISED_RECEIPT_REQUIRED")}

    def record(code, breached):
        if breached is None:
            return
        checks[code]["evaluated"] += 1
        checks[code]["breaches"] += int(bool(breached))

    from api.policy import APPROVAL_THRESHOLDS

    for _, row in expenses.iterrows():
        total = row.get("total")
        has_total = total is not None and not pd.isna(total)
        category = normalise_category(row.get("category"))

        record("CFO_APPROVAL_THRESHOLD",
               (total >= APPROVAL_THRESHOLDS["cfo"]) if has_total else None)
        record("EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF",
               _one_month_late(row.get("date"), row.get("submitted_at")))
        record("MISC_JUSTIFICATION_REQUIRED",
               (category == "MISCELLANEOUS"
                and total >= MISC_JUSTIFICATION_THRESHOLD) if has_total else None)
        line_items = row.get("line_items")
        record("ITEMISED_RECEIPT_REQUIRED",
               (total >= RECEIPT_REQUIRED_THRESHOLD
                and not (isinstance(line_items, list) and line_items))
               if has_total else None)

        # C4's two outcomes only mean something where the handbook actually sets
        # a number for the category.
        if has_total and limit_for(category) is not None:
            assessment = contextual_validation(
                total, category, currency=row.get("currency"))["assessment"]
            record("INFLATION_ADJUSTED_LIMIT_EXCEEDED",
                   assessment == "POLICY_VIOLATION")
            record("OVER_CATEGORY_GUIDELINE", assessment == "OVER_GUIDELINE")

    enforced = {"CFO_APPROVAL_THRESHOLD", "EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF",
                "INFLATION_ADJUSTED_LIMIT_EXCEEDED", "OVER_CATEGORY_GUIDELINE"}
    rows = [{"rule": code, "label": rule_label(code),
             "breaches": v["breaches"], "evaluated": v["evaluated"],
             "enforced": code in enforced}
            for code, v in checks.items()]
    # Ranked by absolute count, never by rate: a rate sort puts whichever rule
    # was evaluated once at the top of "recurring problem areas" every time, and
    # Amara's own phrasing of the problem — "it used to be our most common
    # category" — is a volume claim.
    return (pd.DataFrame(rows, columns=columns)
            .sort_values(["breaches", "evaluated"], ascending=False)
            .reset_index(drop=True))


def repriced_within_todays_money(expenses: pd.DataFrame) -> tuple[int, int]:
    """`(claims over the written figure but inside the re-priced one, base)`.

    This is the brief's "Policy Decay" problem measured: claims that look like
    breaches against a limit last set in 2019 and are entirely normal at 2026
    prices. It is what lets Amara tell "our people got worse" apart from "our
    rules got older", and it is a count with its base rather than a chart —
    the base is only the receipts in a category the handbook actually caps.
    """
    if expenses is None or expenses.empty:
        return 0, 0
    good, base = 0, 0
    for _, row in expenses.iterrows():
        total = row.get("total")
        if total is None or pd.isna(total):
            continue
        category = normalise_category(row.get("category"))
        if limit_for(category) is None:
            continue
        base += 1
        if contextual_validation(total, category,
                                 currency=row.get("currency"))["assessment"] == "GOOD_DEAL":
            good += 1
    return good, base


def breakdown(expenses: pd.DataFrame, column: str) -> pd.DataFrame:
    """Receipts and states grouped by `category` or `submitter`.

    Categories are normalised first: the live sheet holds `Travel` and
    `Subsistence` from n8n while `/api/audit` writes `travel` lowercase, and
    grouping the raw column would split one category across several rows.
    """
    columns = ["receipts", "assessed", CLEARED, NEEDS_REVIEW, NEVER_ASSESSED,
               "review_rate"]
    empty = pd.DataFrame(columns=columns)
    empty.index.name = column
    if expenses is None or expenses.empty:
        return empty

    df = expenses.copy()
    key = (df["category"].map(normalise_category) if column == "category"
           else df[column].astype("string").fillna("(not recorded)"))
    df = df.assign(_key=key)
    df["state"] = df["verdict"].map(verdict_state)

    counts = (df.groupby(["_key", "state"]).size().unstack(fill_value=0)
              .reindex(columns=list(STATES), fill_value=0)
              .astype(int))
    counts["receipts"] = counts[list(STATES)].sum(axis=1)
    counts["assessed"] = counts[CLEARED] + counts[NEEDS_REVIEW]
    counts["review_rate"] = [
        (float("nan") if row["assessed"] < MIN_RATE_BASE
         else row[NEEDS_REVIEW] / row["assessed"])
        for _, row in counts.iterrows()]
    counts.index.name = column
    return (counts[columns]
            .sort_values([NEEDS_REVIEW, "receipts"], ascending=False))
