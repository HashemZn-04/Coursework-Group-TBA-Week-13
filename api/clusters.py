"""
I1 — "Syndicated Spending" detection (stretch goal, P2).

The ticket asks for groups of employees "consistently submitting similar
non-flagged expenses", with "a documented similarity basis". Amara described two
patterns and they are not the same shape:

* **Syndicated** — "are they passing this around between them", meaning several
  employees each submitting part of one shared expense. Handbook 10.2 names it:
  "clustering of similar claims across multiple employees on the same date", and
  9.2 says the aggregation rule "exists principally to deter [...] the practice
  sometimes referred to as split-receipting".
* **Duplicate** — the same person claiming the same thing twice. Her method
  today is recognising a receipt she has seen before while working through a
  pile: "that would just be, like, a way to look back at other ones submitted by
  the same person."

Both come out of the same grouping, because both are "these claims are the same
claim". Only the submitter count tells them apart, so this finds the groups once
and labels each.

**Why the similarity is computed by hand and only the grouping is learned.** The
acceptance criterion is a *documented* similarity basis — a reviewer has to be
able to see why two claims were put together, and a centroid in feature space is
not an answer to that. So the distance between two claims is defined here in
named units: how far apart the amounts are as a share of the tolerance, and how
many days apart the dates are as a share of the window. `DBSCAN` then does the
grouping, which is the part worth borrowing: it needs no `k` up front, it forms
groups transitively, and — unlike KMeans — it is allowed to leave a claim in no
group at all, which is the answer for most claims.

**What stops it crying wolf**, which is what QA's I3 ticket exists to attack:

* Claims only ever group with claims from the **same merchant and the same
  currency**. Merchant names are normalised first, because the live sheet holds
  `WAL*MART`, `WAL-MART` and `Walmart` for one shop — but a name that
  normalises to nothing, or to a single short token, matches nothing rather than
  matching everything.
* Dates must be **within a few days**. Handbook 10.2's concern is same-date
  clustering; a team that legitimately expenses one approved vendor month after
  month does not group, because those claims are months apart.
* A group is only raised **for review** when something makes it worth Amara's
  time: an exact repeat by one person, a material amount, or claiming on more
  than one date. Two colleagues buying coffee at the same place on the same
  morning meets none of those, and is reported as immaterial rather than hidden
  — hiding it would make the guard impossible to audit.

**What it cannot do.** Thresholds are GBP and the sample data is USD, and
nothing converts (Handbook 12.2), so a non-GBP group says so instead of
pretending the comparison holds. And this sees only what the sheet holds: a
split purchase whose halves were bought from different merchants is invisible
here, which is why the governance prompt also asks the model to flag suspicion.
"""

import re
from dataclasses import dataclass

import pandas as pd
from sklearn.cluster import DBSCAN

from api.policy import (APPROVAL_THRESHOLDS, RECEIPT_REQUIRED_THRESHOLD,
                        REPORTING_CURRENCY)

#: Two amounts are "the same amount" within the larger of these. The percentage
#: absorbs a genuinely split bill that did not divide evenly; the absolute floor
#: keeps small claims from being separated by rounding. Both are ours — the
#: handbook sets no similarity tolerance anywhere.
AMOUNT_TOLERANCE_PCT = 0.02
AMOUNT_TOLERANCE_ABS = 0.50

#: How far apart two claims can be dated and still be one event. Handbook 10.2's
#: wording is "on the same date"; three days allows for a bill settled the
#: morning after and for receipts dated by the card rather than the meal.
DATE_WINDOW_DAYS = 3

#: A group is raised for review when its total reaches the line-manager
#: threshold (£250, Handbook 9.1 and Amara's current figure), or when a single
#: claim in it reaches the itemised-receipt threshold (£25, Handbook 8.1), or
#: when the same person filed the identical claim more than once, or when the
#: group spans more than one date. Below all of those it is reported as
#: immaterial rather than dropped.
MATERIAL_GROUP_TOTAL = APPROVAL_THRESHOLDS["line_manager"]
MATERIAL_CLAIM_AMOUNT = RECEIPT_REQUIRED_THRESHOLD

SYNDICATED = "SYNDICATED"
DUPLICATE = "DUPLICATE"

REVIEW = "review"
IMMATERIAL = "immaterial"

#: Words that carry no identity, stripped before merchants are compared.
_MERCHANT_NOISE = {"LTD", "LIMITED", "PLC", "INC", "LLC", "CO", "COMPANY",
                   "THE", "STORE", "STORES", "SUPERCENTER", "SUPERCENTRE",
                   "SUPERMARKET", "GROUP", "UK", "USA"}

#: A key this short is not an identity. An unreadable merchant reduces to
#: nothing at all, and a name made only of noise words (`The Ltd`) reduces to
#: nothing too — matching on either would group every unreadable receipt with
#: every other one, which is the failure mode that would discredit the whole
#: page on first contact.
MIN_MERCHANT_KEY_LENGTH = 3

#: A branch number, which identifies a shop rather than a chain — dropped so
#: that `WAL-MART STORE #5260` and `WAL*MART` are the same merchant. Digits that
#: are part of the name itself are kept, so `Cafe 22` and `Cafe 55` stay
#: distinct.
_BRANCH_NUMBER = re.compile(r"#\s*\d+")


@dataclass(frozen=True)
class Pattern:
    """One group of claims that look like the same claim."""

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
    """A merchant name reduced to what is worth comparing.

    Verified against the live sheet, where one shop appears as `WAL*MART`,
    `WAL-MART` and `Walmart`: all three reduce to `WALMART`, as does
    `WAL-MART STORE #5260`, because a branch number identifies a shop rather
    than a chain. Digits that are part of the name itself are kept, so `Cafe 22`
    and `Cafe 55` do not collapse into one merchant — over-grouping is the more
    damaging error of the two.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    cleaned = _BRANCH_NUMBER.sub(" ", str(name).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", cleaned).split()
    kept = [t for t in tokens if t not in _MERCHANT_NOISE]
    return "".join(kept or tokens)


def _distance(a: pd.Series, b: pd.Series) -> float:
    """How far apart two claims are, in multiples of their own tolerance.

    1.0 is exactly at the limit on whichever axis is worse, so a threshold of
    1.0 means "inside both tolerances". Expressing it this way is what makes the
    grouping explainable: the number has units a reviewer can read.
    """
    tolerance = max(AMOUNT_TOLERANCE_PCT * max(abs(a["total"]), abs(b["total"])),
                    AMOUNT_TOLERANCE_ABS)
    amount = abs(a["total"] - b["total"]) / tolerance
    days = abs((a["date"] - b["date"]).days)
    return max(amount, days / DATE_WINDOW_DAYS)


def _severity(total: float, amounts: list, dates: set, repeats: dict) -> tuple:
    """`(severity, sentence)` — whether this group is worth a reviewer's time.

    The thresholds it weighs against are the handbook's own, and they are
    `REPORTING_CURRENCY`; the caller adds the unconverted-currency caveat when
    the claims are in something else.
    """
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
    """Groups of claims that look like the same claim, most serious first.

    Takes `dashboard.data.load_expenses()`; pure, no sheet access. Claims with
    no readable merchant, amount or date cannot be compared and are simply not
    grouped — they are still in every other view.
    """
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
                d = _distance(block.loc[i], block.loc[j])
                matrix[i][j] = matrix[j][i] = d

        labels = DBSCAN(eps=1.0, min_samples=2,
                        metric="precomputed").fit_predict(matrix)
        for label in sorted(set(labels)):
            if label == -1:      # DBSCAN's noise label: in no group, which is
                continue         # the right answer for most claims.
            members = block[labels == label]
            submitters = sorted({str(s) for s in members["submitter"].fillna("")})
            dates = {d.date().isoformat() for d in members["date"]}
            amounts = [float(a) for a in members["total"]]
            total = float(sum(amounts))

            # An exact repeat is the same person, same amount, same day — the
            # thing Amara catches by recognising a receipt she has seen before.
            repeats = {}
            for submitter, rows in members.groupby(members["submitter"].fillna("")):
                identical = rows.groupby([rows["total"].round(2),
                                          rows["date"].dt.date]).size()
                worst = int(identical.max()) if len(identical) else 0
                if worst > 1:
                    repeats[str(submitter)] = worst

            severity, judgement = _severity(total, amounts, dates, repeats)
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

    # Review-worthy first, then by value, then by size — so the page opens on
    # the thing most worth Amara's time rather than on the biggest coincidence.
    return sorted(patterns,
                  key=lambda p: (p.severity != REVIEW, -p.total, -p.receipts))


def pattern_identity(receipt_ids) -> str:
    """The key a review is recorded against: exactly which claims were reviewed.

    Deliberately membership-defined. If the group later gains a claim, the key
    changes and the group comes back unreviewed — which is correct, because a
    new member is new information and Amara cleared a different set. Keying on
    anything membership-independent would silently keep a stale "reviewed" mark
    over a group that has grown.
    """
    return ",".join(str(int(r)) for r in sorted(receipt_ids))
