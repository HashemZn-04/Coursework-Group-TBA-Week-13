from dataclasses import dataclass

import pandas as pd

from api.policy import VERDICT_HIGH, VERDICTS

# Bucket used when a row records no currency code at all — kept separate
# rather than folded into the commonest one.
UNKNOWN_CURRENCY = ""

# Every receipt lands in exactly one bucket, so the four money columns plus
# the two data-quality ones always sum back to `claimed`.
BUCKETS = ("approved", "at_risk", "prevented", "unprocessed", "unrecognised",
           "ambiguous")

# Bucket sizes tried in order for the spend-velocity chart, widening until the
# chart has few enough bars to read.
FREQ_LADDER = ("D", "W", "MS", "QS", "YS")

# Roughly the number of bars that stay individually readable at Streamlit's
# default chart width.
MAX_CHART_BARS = 45


@dataclass(frozen=True)
class SpendSummary:
    """`totals` indexed by currency code, with a money column and a
    `*_count` column per bucket, plus `claimed`/`claimed_count`."""

    totals: pd.DataFrame
    undated_rejections: int = 0
    duplicate_receipt_ids: int = 0

    @property
    def currencies(self) -> list[str]:
        # Ordered by receipt count, not amount — ranking by amount would
        # compare 450 USD against 264 GBP, the comparison this module refuses.
        if self.totals.empty:
            return []
        return list(self.totals.sort_values(
            ["claimed_count", "claimed"], ascending=False).index)


def currency_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return UNKNOWN_CURRENCY
    return str(value).strip().upper()


def bucket_for(verdict, status) -> str:
    # A missing verdict is checked before status: nothing assessed that
    # receipt, so it cannot be an outcome of the audit.
    if verdict is None or (isinstance(verdict, float) and pd.isna(verdict)) \
            or verdict is pd.NA or str(verdict).strip() == "":
        return "unprocessed"
    verdict = str(verdict)
    if verdict not in VERDICTS:
        return "unrecognised"
    status = str(status or "").strip().lower()
    if status == "rejected":
        return "prevented"
    if status == "approved":
        return "approved"
    return "at_risk" if verdict == VERDICT_HIGH else "approved"


def spend_summary(expenses: pd.DataFrame) -> SpendSummary:
    columns = ["claimed", "claimed_count"] + [
        c for b in BUCKETS for c in (b, f"{b}_count")]
    empty = pd.DataFrame(columns=columns, dtype="float64")
    empty.index.name = "currency"

    if expenses is None or expenses.empty:
        return SpendSummary(totals=empty)

    df = expenses.copy()
    df["currency_key"] = df["currency"].map(currency_key) if "currency" in df \
        else UNKNOWN_CURRENCY
    df["amount"] = pd.to_numeric(df.get("total"), errors="coerce").fillna(0.0)

    # A receipt id missing or shared with another row cannot be trusted as an
    # identity, so its outcome is held out of the buckets. It stays in
    # `claimed` — somebody really did claim that money.
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
        buckets.append(bucket_for(verdicts.loc[idx], statuses.loc[idx]))
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


def default_currency(currencies: list[str]) -> str:
    if not currencies:
        return UNKNOWN_CURRENCY
    return "GBP" if "GBP" in currencies else currencies[0]


def choose_freq(dates: pd.Series) -> str:
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
    columns = {"spend": pd.Series(dtype="float64"),
               "receipts": pd.Series(dtype="int64")}
    if expenses is None or expenses.empty:
        return pd.DataFrame(columns)

    df = expenses[expenses["currency"].map(
        currency_key) == currency_key(currency)]
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
    """Cumulative money prevented, indexed by the date of the rejection
    (not the receipt date — the money was stopped when Amara clicked)."""
    if expenses is None or expenses.empty:
        return pd.Series(dtype="float64")

    rejected = expenses[(expenses["status"].astype("string").str.strip().str.lower()
                         == "rejected")
                        & (expenses["currency"].map(currency_key)
                           == currency_key(currency))
                        & expenses["decided_at"].notna()]
    if rejected.empty:
        return pd.Series(dtype="float64")

    by_date = (rejected.set_index("decided_at").sort_index()["total"]
               .groupby(level=0).sum().cumsum())
    by_date.index.name = "decided_at"
    return by_date
