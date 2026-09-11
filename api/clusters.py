import re
from dataclasses import dataclass

import pandas as pd
from sklearn.cluster import DBSCAN

from api.policy import (APPROVAL_THRESHOLDS, RECEIPT_REQUIRED_THRESHOLD,
                        REPORTING_CURRENCY)

# Two amounts are "the same amount" within the larger of these.
AMOUNT_TOLERANCE_PCT = 0.02
AMOUNT_TOLERANCE_ABS = 0.50

# How far apart two claims can be dated and still be one event (Handbook 10.2).
DATE_WINDOW_DAYS = 3

# A group is raised for review at the line-manager threshold, the
# itemised-receipt threshold, an exact repeat, or spanning more than one date.
MATERIAL_GROUP_TOTAL = APPROVAL_THRESHOLDS["line_manager"]
MATERIAL_CLAIM_AMOUNT = RECEIPT_REQUIRED_THRESHOLD

SYNDICATED = "SYNDICATED"
DUPLICATE = "DUPLICATE"

REVIEW = "review"
IMMATERIAL = "immaterial"

_MERCHANT_NOISE = {"LTD", "LIMITED", "PLC", "INC", "LLC", "CO", "COMPANY",
                   "THE", "STORE", "STORES", "SUPERCENTER", "SUPERCENTRE",
                   "SUPERMARKET", "GROUP", "UK", "USA"}

# A key this short is not an identity — matching on it would group every
# unreadable receipt with every other one.
MIN_MERCHANT_KEY_LENGTH = 3

# A branch number identifies a shop rather than a chain, so it's dropped
# (WAL-MART STORE #5260 == WAL*MART). Digits in the name itself are kept.
_BRANCH_NUMBER = re.compile(r"#\s*\d+")


@dataclass(frozen=True)
class Pattern:
    pattern: str
    merchant: str
    merchant_key: str
    currency: str
    receipt_ids: tuple
    submitters: tuple
    receipts: int
    total: float
    dates: tuple
    severity: str
    basis: str
    unconverted_currency: bool
    exact_repeats: dict


def merchant_key(name) -> str:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    cleaned = _BRANCH_NUMBER.sub(" ", str(name).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", cleaned).split()
    kept = [t for t in tokens if t not in _MERCHANT_NOISE]
    return "".join(kept or tokens)


def distance(a: pd.Series, b: pd.Series) -> float:
    """Multiples of tolerance apart; 1.0 = exactly at the limit."""
    tolerance = max(AMOUNT_TOLERANCE_PCT * max(abs(a["total"]), abs(b["total"])),
                    AMOUNT_TOLERANCE_ABS)
    amount = abs(a["total"] - b["total"]) / tolerance
    days = abs((a["date"] - b["date"]).days)
    return max(amount, days / DATE_WINDOW_DAYS)


def classify_severity(total: float, amounts: list, dates: set, repeats: dict) -> tuple:
    reasons = []
    if repeats:
        reasons.append("the identical claim was filed more than once by the "
                       "same person")
    if total >= MATERIAL_GROUP_TOTAL:
        reasons.append(f"the group totals at or above the £{MATERIAL_GROUP_TOTAL:,.0f} "
                       f"line-manager approval threshold (Handbook 9.1)")
    if any(a >= MATERIAL_CLAIM_AMOUNT for a in amounts):
        reasons.append(f"at least one claim is at or above the "
                       f"£{MATERIAL_CLAIM_AMOUNT:,.0f} itemised-receipt "
                       f"threshold (Handbook 8.1)")
    if len(dates) > 1:
        reasons.append("the claims fall on more than one date")
    if reasons:
        return REVIEW, "Raised because " + "; ".join(reasons) + "."
    return IMMATERIAL, (
        f"Not raised: every claim is below the £{MATERIAL_CLAIM_AMOUNT:,.0f} "
        f"itemised-receipt threshold, the group totals under £"
        f"{MATERIAL_GROUP_TOTAL:,.0f}, they all fall on one date, and nobody "
        f"filed the same claim twice.")


def find_patterns(expenses: pd.DataFrame) -> list[Pattern]:
    if expenses is None or expenses.empty:
        return []

    df = expenses.dropna(subset=["total", "date"]).copy()
    if df.empty:
        return []
    df["_merchant_key"] = df["merchant"].map(merchant_key)
    df["_currency"] = (df["currency"].astype("string").fillna("")
                       .str.strip().str.upper())
    df = df[df["_merchant_key"].str.len() >= MIN_MERCHANT_KEY_LENGTH]
    if df.empty:
        return []

    patterns = []
    for (key, currency), block in df.groupby(["_merchant_key", "_currency"]):
        if len(block) < 2:
            continue
        block = block.reset_index(drop=True)
        size = len(block)
        matrix = [[0.0] * size for _ in range(size)]
        for i in range(size):
            for j in range(i + 1, size):
                d = distance(block.loc[i], block.loc[j])
                matrix[i][j] = matrix[j][i] = d

        labels = DBSCAN(eps=1.0, min_samples=2,
                        metric="precomputed").fit_predict(matrix)
        for label in sorted(set(labels)):
            if label == -1:      # DBSCAN's noise label: not in any group.
                continue
            members = block[labels == label]
            submitters = sorted({str(s) for s in members["submitter"].fillna("")})
            dates = {d.date().isoformat() for d in members["date"]}
            amounts = [float(a) for a in members["total"]]
            total = float(sum(amounts))

            repeats = {}
            for submitter, rows in members.groupby(members["submitter"].fillna("")):
                identical = rows.groupby([rows["total"].round(2),
                                          rows["date"].dt.date]).size()
                worst = int(identical.max()) if len(identical) else 0
                if worst > 1:
                    repeats[str(submitter)] = worst

            severity, judgement = classify_severity(total, amounts, dates, repeats)
            unconverted = bool(currency) and currency != REPORTING_CURRENCY
            span = (max(dates) if len(dates) > 1 else next(iter(dates)))
            basis = (
                f"{len(members)} claims at {members['merchant'].iloc[0]} "
                f"({key}), {min(amounts):,.2f}–{max(amounts):,.2f} {currency or 'no currency'}, "
                f"{'dated ' + next(iter(dates)) if len(dates) == 1 else f'between {min(dates)} and {span}'}, "
                f"from {len(submitters)} submitter(s). Grouped because every "
                f"pair is within {AMOUNT_TOLERANCE_PCT:.0%} (or "
                f"{AMOUNT_TOLERANCE_ABS:.2f}) on amount and "
                f"{DATE_WINDOW_DAYS} days on date. " + judgement
            )
            if unconverted:
                basis += (f" The thresholds behind that judgement are "
                          f"{REPORTING_CURRENCY} and these claims are "
                          f"{currency}; nothing converts between them "
                          f"(Handbook 12.2), so weigh the rate yourself.")

            patterns.append(Pattern(
                pattern=SYNDICATED if len([s for s in submitters if s]) > 1
                else DUPLICATE,
                merchant=str(members["merchant"].iloc[0]),
                merchant_key=key,
                currency=currency,
                receipt_ids=tuple(sorted(
                    int(r) for r in members["receipt_id"].dropna())),
                submitters=tuple(submitters),
                receipts=len(members),
                total=round(total, 2),
                dates=tuple(sorted(dates)),
                severity=severity,
                basis=basis,
                unconverted_currency=unconverted,
                exact_repeats=repeats,
            ))

    return sorted(patterns,
                  key=lambda p: (p.severity != REVIEW, -p.total, -p.receipts))


def pattern_identity(receipt_ids) -> str:
    """Key a review is recorded against — the exact set of claims reviewed."""
    return ",".join(str(int(r)) for r in sorted(receipt_ids))
