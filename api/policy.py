"""
Handbook-derived spend limits — the *static* half of C4 (MCP-27).

Every figure here traces to a section of `discovery_docs/MCG_expense_policy_final_2.md`
(the 2019 handbook plus its addenda) or to a figure Amara confirmed live in the
stakeholder interview (`discovery_docs/transcript.md`). Each limit carries the
period it was last set in, because C4's whole point is that a 2019 figure is not
a 2026 figure: `api.audit` re-prices these against CPI before comparing them to a
receipt.

Two provenance notes worth keeping straight:

* Addendum B (January 2022) uplifted subsistence (3.1), mileage (4.4) and staff
  entertainment (6.2) by 15%. Addendum C clarified the uplift applies to the
  original 2019 base figures, not to already-London-weighted ones. So those
  limits are stored post-uplift with a 2022-01 base period. Addendum B
  explicitly did *not* uplift client entertainment (5.2), which therefore keeps
  its 2019-03 base — it is the staleset figure in the book and the one most
  likely to produce a "good deal" reading.
* The approval thresholds in Section 9.1 (£250 / £1,000) are superseded by what
  Amara actually enforces: £250 line-manager, £2,000 CFO ("the CFO approval used
  to be over a thousand. It's over two thousand now"). Those are current figures,
  not stale ones, so they are *not* inflation-adjusted — they are gates, not
  price ceilings. They live here for traceability; n8n's "Deterministic Policy
  Checks" node is what actually enforces them.

Currency caveat, stated plainly rather than papered over: the handbook is written
in GBP, while the CPI series C4 defaults to (`CPIAUCSL`) is the US index. It is
used as the inflation proxy because it is the only series in FRED that is current
through 2026 — the OECD UK series (`GBRCPIALLMINMEI`) stops in early 2025, which
would defeat the "2026 economic data" requirement in the brief. Set
`CPI_SERIES_ID` in the environment to override.
"""

from dataclasses import dataclass

REPORTING_CURRENCY = "GBP"

#: Addendum B's cost-of-living uplift, applied January 2022.
ADDENDUM_B_UPLIFT = 1.15

#: Period a figure was last set in, as a FRED observation date (month start).
HANDBOOK_ISSUE = "2019-03-01"
ADDENDUM_A_ISSUE = "2020-04-01"
ADDENDUM_B_ISSUE = "2022-01-01"


@dataclass(frozen=True)
class Limit:
    """One numeric ceiling from the handbook.

    `basis` says what the amount is measured against, which decides what C4
    divides the receipt total by before comparing:

    * ``per_claim``  — the whole claim (default)
    * ``per_head``   — divide by attendee count
    * ``per_day``    — divide by number of days claimed
    * ``per_month``  — a recurring monthly charge per licence

    `hard` distinguishes a ceiling from a guideline. Section 5.2 is explicit that
    client entertainment figures are "guidelines rather than hard limits"; going
    over one is a conversation, not a violation, so C4 reports it as such.
    """

    category: str
    amount: float
    basis: str
    base_period: str
    source: str
    hard: bool = True
    note: str = ""


#: Keyed by the category enum n8n's "AI Contextual Audit" node returns.
CATEGORY_LIMITS: dict[str, Limit] = {
    "SUBSISTENCE": Limit(
        category="SUBSISTENCE",
        amount=round(40 * ADDENDUM_B_UPLIFT, 2),  # £40 daily total, +15%
        basis="per_day",
        base_period=ADDENDUM_B_ISSUE,
        source="Handbook 3.1 (daily subsistence total), uplifted 15% by Addendum B",
        hard=True,
    ),
    "CLIENT_ENTERTAINMENT": Limit(
        category="CLIENT_ENTERTAINMENT",
        amount=75.0,
        basis="per_head",
        base_period=HANDBOOK_ISSUE,
        source="Handbook 5.2 (standard business meal, per head)",
        hard=False,
        note="Guideline, not a ceiling (5.2). Not uplifted by Addendum B, so this "
             "is the oldest live figure in the handbook.",
    ),
    "STAFF_ENTERTAINMENT": Limit(
        category="STAFF_ENTERTAINMENT",
        amount=round(40 * ADDENDUM_B_UPLIFT, 2),  # £40/head routine social, +15%
        basis="per_head",
        base_period=ADDENDUM_B_ISSUE,
        source="Handbook 6.2 (routine team social, per head), uplifted 15% by Addendum B",
        hard=True,
        note="Rises to £50/head base where alcohol overage applies (6.2).",
    ),
    "SOFTWARE_TECHNOLOGY": Limit(
        category="SOFTWARE_TECHNOLOGY",
        amount=50.0,
        basis="per_month",
        base_period=HANDBOOK_ISSUE,
        source="Handbook 7.1 (pre-approved software, per licence per month)",
        hard=True,
        note="Applies only to software already on the pre-approved list. Anything "
             "not on that list needs manager + IT sign-off before purchase "
             "regardless of cost (7.2) — a limit check cannot clear it.",
    ),
    "PROFESSIONAL_SUBSCRIPTION": Limit(
        category="PROFESSIONAL_SUBSCRIPTION",
        amount=50.0,
        basis="per_month",
        base_period=HANDBOOK_ISSUE,
        source="Handbook 7.1 (pre-approved subscriptions, per licence per month)",
        hard=True,
    ),
}

#: Categories the handbook sets no numeric ceiling for — Travel, Accommodation,
#: Training, Office Supplies, Postage, Miscellaneous, Other. These fall back to
#: the general approval thresholds below rather than to a price comparison.
UNCAPPED_CATEGORIES = (
    "TRAVEL",
    "ACCOMMODATION",
    "TRAINING",
    "OFFICE_SUPPLIES",
    "POSTAGE_COURIER",
    "MISCELLANEOUS",
    "OTHER",
)

#: Per-meal breakdown behind the SUBSISTENCE daily total (3.1, +Addendum B).
MEAL_LIMITS: dict[str, float] = {
    "breakfast": round(12 * ADDENDUM_B_UPLIFT, 2),
    "lunch": round(15 * ADDENDUM_B_UPLIFT, 2),
    "dinner": round(25 * ADDENDUM_B_UPLIFT, 2),
}

#: Current, confirmed by Amara — not handbook figures, not inflation-adjusted.
APPROVAL_THRESHOLDS = {
    "line_manager": 250.0,
    "cfo": 2000.0,
}

#: What the 2019 handbook said, kept for the "policy decay" story in the brief.
HANDBOOK_APPROVAL_THRESHOLDS = {
    "line_manager": 250.0,
    "head_of_finance": 1000.0,
}

#: Miscellaneous claims at or above this need a written justification (2.2).
MISC_JUSTIFICATION_THRESHOLD = 30.0

#: An itemised receipt is required at or above this (8.1).
RECEIPT_REQUIRED_THRESHOLD = 25.0

#: Claims submitted more than this many days after the expense are auto-rejected.
#: Amara, asked whether to keep or tighten it: "a month feels good [...] they can
#: do it inside a month, or they can deal with it." Enforced in n8n's
#: deterministic layer as one calendar month; recorded here for traceability.
SUBMISSION_WINDOW_DAYS = 30


def limit_for(category: str | None) -> Limit | None:
    """The handbook limit for an audit-engine category, or None if uncapped."""
    if not category:
        return None
    return CATEGORY_LIMITS.get(str(category).strip().upper())


def normalise_category(category: str | None) -> str:
    """Coerce an arbitrary category string onto the audit engine's enum.

    n8n's LLM node is schema-constrained so it always returns one of the enum
    values, but the sheet can be hand-edited and older rows use lowercase, so
    this stays forgiving rather than assuming clean input.
    """
    if not category:
        return "OTHER"
    key = str(category).strip().upper().replace(" ", "_").replace("-", "_")
    if key in CATEGORY_LIMITS or key in UNCAPPED_CATEGORIES:
        return key
    aliases = {
        "TRAVEL_RAIL": "TRAVEL",
        "TRAVEL_AIR": "TRAVEL",
        "TRAVEL_ROAD": "TRAVEL",
        "MILEAGE": "TRAVEL",
        "MEALS": "SUBSISTENCE",
        "FOOD": "SUBSISTENCE",
        "HOTEL": "ACCOMMODATION",
        "SOFTWARE": "SOFTWARE_TECHNOLOGY",
        "TECHNOLOGY": "SOFTWARE_TECHNOLOGY",
        "SUBSCRIPTION": "PROFESSIONAL_SUBSCRIPTION",
        "SUBSCRIPTIONS": "PROFESSIONAL_SUBSCRIPTION",
        "ENTERTAINMENT": "CLIENT_ENTERTAINMENT",
        "MISC": "MISCELLANEOUS",
    }
    return aliases.get(key, "OTHER")
