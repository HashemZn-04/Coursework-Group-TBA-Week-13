"""
E2 — spend velocity and leakage (MCP ticket "Build spend velocity & leakage
visualizations").

The acceptance criterion asks for three things: "total spend over time, spend by
category, and **a running total of leakage prevented**". The first two shipped
with the dashboard shell. The third did not: the tile on Spend Overview summed
the high-risk receipts, which is money **at risk**, not money **saved**. The
difference is not cosmetic — under the old figure, Amara rejecting ten claims
moved the "leakage" number by nothing at all, because a rejected claim is still
a high-risk claim. The one number on the dashboard that was supposed to show the
system paying for itself was structurally incapable of moving.

So this module computes both, side by side, and the page labels them so they
cannot be confused:

* **At risk** — flagged, no decision recorded. Money still on the table.
* **Prevented** — rejected. Money that did not leave the business.

Three rules hold everything else up.

**`status` on the receipt row is the source of truth for money.** There is no
separate Decisions tab any more: `update_decision` overwrites `status` and
stamps `decided_at` on the same row, in place. That means no history of
re-decisions (a reject reversed to an approve simply becomes "approved", with
no record a rejection ever happened) — an accepted tradeoff for a much simpler
schema.

**Aggregate over receipts, never over decision rows.** There is one row per
receipt now, so this is automatic — no double-counting from a double-clicked
button is possible.

**Never add two currencies.** The sheet holds USD receipts and the handbook is
in GBP, and nothing in this pipeline converts between them (Handbook 12.2 wants
the rate on the transaction date; no FX source is wired in). Every figure here
is grouped by currency and rendered through `api.summary.format_money`, so a
total is always attached to the unit it is counted in.

What this deliberately does not do: no £/hour rate, no "N hours saved", no
headcount model. Amara asked for exactly two numbers — "how much would this cost
and how much time would this save us [...] I don't need calculations beyond
that" — and was explicit that she is "not planning on reducing headcount". Those
two numbers belong in the deck. This page shows money that moved and money that
did not.
"""

from dataclasses import dataclass

import pandas as pd

from api.policy import VERDICT_HIGH, VERDICTS

#: The currency bucket used when a row records no currency code at all. Kept as
#: its own bucket rather than folded into the commonest one — a receipt with no
#: unit recorded is not evidence that it shares everybody else's.
UNKNOWN_CURRENCY = ""

#: Outcome buckets. Every receipt lands in exactly one, so the four money
#: columns plus the two data-quality ones always sum back to `claimed`. That
#: identity is what `tests/test_spend.py` asserts, and it is the only defence
#: against a double-count quietly inflating the saving figure.
BUCKETS = ("approved", "at_risk", "prevented", "unprocessed", "unrecognised",
           "ambiguous")

#: Bucket sizes tried in order for the spend-velocity chart, widening until the
#: chart has few enough bars to read.
FREQ_LADDER = ("D", "W", "MS", "QS", "YS")

#: Roughly the number of bars that stay individually readable at Streamlit's
#: default chart width. Ours, not a figure from anywhere — it is a legibility
#: choice, not a policy one. Deliberately not 60: `CACHE_TTL` and the Sheets
#: read quota are both 60 and mean entirely different things.
MAX_CHART_BARS = 45


@dataclass(frozen=True)
class SpendSummary:
    """Money by outcome, per currency, plus what could not be counted.

    `totals` is indexed by currency code (`UNKNOWN_CURRENCY` for rows with none)
    with a money column and a `*_count` column per bucket, plus `claimed` and
    `claimed_count`. The counters below are the things that would otherwise be
    silently dropped; the page reports each one that is non-zero, because a
    figure that quietly excludes rows is the failure mode this whole dashboard
    keeps guarding against.
    """

    totals: pd.DataFrame
    undated_rejections: int = 0
    duplicate_receipt_ids: int = 0

    @property
    def currencies(self) -> list[str]:
        """Currency codes present, commonest first.

        Ordered by receipt count rather than by amount: ranking by amount would
        compare 450 USD against 264 GBP, which is the comparison this module
        exists to refuse.
        """
        if self.totals.empty:
            return []
        return list(self.totals.sort_values(
            ["claimed_count", "claimed"], ascending=False).index)


def _currency_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return UNKNOWN_CURRENCY
    return str(value).strip().upper()


def _bucket_for(verdict, status) -> str:
    """Which outcome a receipt belongs to. First match wins, so this is a
    partition by construction.

    The order matters in one place especially: a missing verdict is checked
    *before* status. Nothing assessed that receipt, so it cannot be an outcome
    of the audit — `normalise_verdict`'s docstring is explicit that a missing
    verdict is a processing failure and never something to resolve into a
    bucket.
    """
    if verdict is None or (isinstance(verdict, float) and pd.isna(verdict)) \
            or verdict is pd.NA or str(verdict).strip() == "":
        return "unprocessed"
    verdict = str(verdict)
    if verdict not in VERDICTS:
        # `normalise_verdict` passes an unrecognised value through verbatim, so
        # a typo in the sheet is neither `low_risk`, nor `high_risk`, nor
        # absent. It gets its own bucket so the columns still sum to `claimed`
        # instead of the row vanishing out of a page whose whole claim is that
        # its arithmetic is honest.
        return "unrecognised"
    status = str(status or "").strip().lower()
    if status == "rejected":
        return "prevented"
    if status == "approved":
        return "approved"
    # Still pending_review: the verdict alone says where it sits. `low_risk` is
    # approved by the engine at audit time and should never be pending_review,
    # but if a row is malformed this still resolves it towards a safe bucket.
    return "at_risk" if verdict == VERDICT_HIGH else "approved"


def spend_summary(expenses: pd.DataFrame) -> SpendSummary:
    """Claimed / approved / at-risk / prevented, per currency.

    `expenses` is `dashboard.data.load_expenses()`, already cached by its
    loader, so this stays a pure function over a frame — no sheet reads,
    nothing to cache, and testable against a hand-built frame.
    """
    columns = ["claimed", "claimed_count"] + [
        c for b in BUCKETS for c in (b, f"{b}_count")]
    empty = pd.DataFrame(columns=columns, dtype="float64")
    empty.index.name = "currency"

    if expenses is None or expenses.empty:
        return SpendSummary(totals=empty)

    df = expenses.copy()
    df["currency_key"] = df["currency"].map(_currency_key) if "currency" in df \
        else UNKNOWN_CURRENCY
    df["amount"] = pd.to_numeric(df.get("total"), errors="coerce").fillna(0.0)

    # A receipt id that is missing or shared with another row cannot be trusted
    # as an identity, so its outcome is held out of the buckets rather than
    # guessed at. Those receipts stay in `claimed` — somebody really did claim
    # that money.
    ids = df["receipt_id"] if "receipt_id" in df else pd.Series(
        pd.NA, index=df.index)
    duplicated = ids.duplicated(keep=False) & ids.notna()
    ambiguous = duplicated | ids.isna()

    verdicts = df["verdict"] if "verdict" in df else pd.Series(
        None, index=df.index)
    statuses = df["status"] if "status" in df else pd.Series(
        None, index=df.index)
    buckets = []
    for idx in df.index:
        if ambiguous.loc[idx]:
            buckets.append("ambiguous")
            continue
        buckets.append(_bucket_for(verdicts.loc[idx], statuses.loc[idx]))
    df["bucket"] = buckets

    totals = pd.DataFrame(index=pd.Index(sorted(df["currency_key"].unique()),
                                         name="currency"))
    grouped = df.groupby("currency_key")
    totals["claimed"] = grouped["amount"].sum()
    totals["claimed_count"] = grouped.size()
    for bucket in BUCKETS:
        rows = df[df["bucket"] == bucket].groupby("currency_key")
        totals[bucket] = rows["amount"].sum().reindex(totals.index).fillna(0.0)
        totals[f"{bucket}_count"] = (rows.size().reindex(totals.index)
                                     .fillna(0).astype(int))
    totals["claimed"] = totals["claimed"].fillna(0.0)
    totals["claimed_count"] = totals["claimed_count"].fillna(0).astype(int)

    rejected = df[df["bucket"] == "prevented"]
    undated = int(rejected["decided_at"].isna().sum()
                  ) if not rejected.empty else 0

    return SpendSummary(
        totals=totals,
        undated_rejections=undated,
        duplicate_receipt_ids=int(duplicated.sum()),
    )


def choose_freq(dates: pd.Series) -> str:
    """The widest bucket that still fits inside `MAX_CHART_BARS`.

    A month of Meridian claims lands on daily buckets; the SROIE sample's
    2010-to-2026 span lands on yearly ones. Picking the grain from the data
    rather than offering a selector is deliberate: Streamlit re-runs the whole
    script on every widget interaction, and with the sheet this size no grain
    changes the answer.
    """
    dates = pd.Series(dates).dropna()
    if dates.empty:
        return FREQ_LADDER[0]
    start, end = dates.min(), dates.max()
    for freq in FREQ_LADDER:
        if len(pd.date_range(start, end, freq=freq)) + 1 <= MAX_CHART_BARS:
            return freq
    return FREQ_LADDER[-1]


def spend_over_time(expenses: pd.DataFrame, currency: str,
                    freq: str | None = None) -> pd.DataFrame:
    """Spend per calendar bucket — the actual velocity figure.

    The chart this replaces plotted one point per receipt against its date and
    joined them with a line. That is a scatter of individual claim sizes, not a
    rate: on the live sheet seven receipts share the timestamp
    `08/20/10 13:12:01`, so seven points stacked on one x-value and the "line"
    was a vertical spike in arbitrary order. Spend per period is the rate.

    Empty periods are zero-filled rather than dropped, because a month with no
    claims is a fact about velocity.

    Returns a frame indexed by period start with `spend` and `receipts`. Chart
    `spend`; `receipts` belongs in a caption, not on the same axis as money.
    """
    columns = {"spend": pd.Series(dtype="float64"),
               "receipts": pd.Series(dtype="int64")}
    if expenses is None or expenses.empty:
        return pd.DataFrame(columns)

    df = expenses[expenses["currency"].map(
        _currency_key) == _currency_key(currency)]
    df = df[df["date"].notna()]
    if df.empty:
        return pd.DataFrame(columns)

    freq = freq or choose_freq(df["date"])
    grouped = df.set_index("date").resample(freq).agg(
        spend=("total", "sum"), receipts=("total", "size"))
    grouped["spend"] = grouped["spend"].fillna(0.0)
    grouped["receipts"] = grouped["receipts"].fillna(0).astype(int)
    return grouped


def prevented_running_total(expenses: pd.DataFrame, currency: str) -> pd.Series:
    """Cumulative money prevented, indexed by the date of the rejection.

    Plotted against `decided_at`, not the receipt date: the money was stopped
    when Amara clicked, not when the meal was eaten.

    Built from each receipt's current `status`, so it is a restated as-of-now
    picture rather than an event log — reversing a rejection lowers the whole
    curve from that point on, which is right, because the tile and the chart
    have to agree. A rejection with no readable `decided_at` counts in the tile
    but has nowhere to sit on this axis, so the curve can end below the tile;
    the page reports that gap rather than quietly reconciling it.
    """
    if expenses is None or expenses.empty:
        return pd.Series(dtype="float64")

    rejected = expenses[(expenses["status"].astype("string").str.strip().str.lower()
                         == "rejected")
                        & (expenses["currency"].map(_currency_key)
                           == _currency_key(currency))
                        & expenses["decided_at"].notna()]
    if rejected.empty:
        return pd.Series(dtype="float64")

    by_date = (rejected.set_index("decided_at").sort_index()["total"]
               .groupby(level=0).sum().cumsum())
    by_date.index.name = "decided_at"
    return by_date
