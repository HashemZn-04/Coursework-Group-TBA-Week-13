import pandas as pd

from api.audit import contextual_validation
from api.policy import (MISC_JUSTIFICATION_THRESHOLD,
                        RECEIPT_REQUIRED_THRESHOLD, VERDICT_HIGH, VERDICT_LOW,
                        limit_for, normalise_category)
from api.summary import FLAG_DESCRIPTIONS, VERDICT_HEADLINES

# never_assessed is not a verdict: a missing verdict means the pipeline never
# finished, and is kept out of both the numerator and denominator of every rate.
CLEARED = "cleared"
NEEDS_REVIEW = "needs_review"
NEVER_ASSESSED = "never_assessed"
UNRECOGNISED = "unrecognised"
STATES = (CLEARED, NEEDS_REVIEW, NEVER_ASSESSED, UNRECOGNISED)

STATE_LABELS = {
    CLEARED: VERDICT_HEADLINES[VERDICT_LOW],
    NEEDS_REVIEW: VERDICT_HEADLINES[VERDICT_HIGH],
    NEVER_ASSESSED: "Never assessed",
    UNRECOGNISED: "Unrecognised verdict",
}

# Below this many assessed receipts, a percentage is not shown at all.
MIN_RATE_BASE = 5

# Fewer populated months than this and the chart is a composition, not a trend.
MIN_TREND_PERIODS = 3
MAX_TREND_GAP_MONTHS = 12

# Rules the dashboard re-checks. `enforced` says whether the live pipeline
# checks this rule too — the last two are in the handbook and nothing else.
_HANDBOOK_LABELS = {
    "MISC_JUSTIFICATION_REQUIRED":
        f"coded to Miscellaneous at or above £{MISC_JUSTIFICATION_THRESHOLD:,.0f}, "
        "which needs a written justification (Handbook 2.2)",
    "ITEMISED_RECEIPT_REQUIRED":
        f"at or above £{RECEIPT_REQUIRED_THRESHOLD:,.0f} with no itemised lines "
        "captured, where policy requires an itemised receipt (Handbook 8.1)",
}


def rule_label(code: str) -> str:
    return FLAG_DESCRIPTIONS.get(code) or _HANDBOOK_LABELS.get(code) or code


def verdict_state(verdict) -> str:
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
    assessed = cleared + needs_review
    if assessed < MIN_RATE_BASE:
        return float("nan")
    return cleared / assessed


def compliance_trend(expenses: pd.DataFrame) -> pd.DataFrame:
    """Bucketed on receipt_date (when the money was spent), not on when the
    verdict was recorded — otherwise clearing a backlog reads as a trend."""
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
    if trend.empty:
        return True
    if len(trend) < MIN_TREND_PERIODS:
        return True
    months = pd.PeriodIndex(trend.index, freq="M")
    if len(months) < 2:
        return True
    gaps = [(months[i + 1] - months[i]).n for i in range(len(months) - 1)]
    return max(gaps) > MAX_TREND_GAP_MONTHS


def one_month_late(spent, submitted) -> bool | None:
    if pd.isna(spent) or pd.isna(submitted):
        return None
    return submitted > spent + pd.DateOffset(months=1)


def rule_breaches(expenses: pd.DataFrame) -> pd.DataFrame:
    """Each rule carries its own base — most cannot be evaluated against
    every receipt. A receipt can break several rules and is counted once
    under each, so the column does not sum to the receipt count."""
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
               one_month_late(row.get("date"), row.get("submitted_at")))
        record("MISC_JUSTIFICATION_REQUIRED",
               (category == "MISCELLANEOUS"
                and total >= MISC_JUSTIFICATION_THRESHOLD) if has_total else None)
        line_items = row.get("line_items")
        record("ITEMISED_RECEIPT_REQUIRED",
               (total >= RECEIPT_REQUIRED_THRESHOLD
                and not (isinstance(line_items, list) and line_items))
               if has_total else None)

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
    return (pd.DataFrame(rows, columns=columns)
            .sort_values(["breaches", "evaluated"], ascending=False)
            .reset_index(drop=True))


def repriced_within_todays_money(expenses: pd.DataFrame) -> tuple[int, int]:
    """(claims over the written figure but inside the re-priced one, base)."""
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
