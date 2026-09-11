from dataclasses import dataclass

REPORTING_CURRENCY = "GBP"

# Two outcomes, not three. low_risk auto-approves and never reaches a human;
# high_risk goes to the review queue. n8n's MEDIUM risk level maps to
# high_risk for the same reason. status on the Receipts row (pending_review ->
# approved/rejected) is the decision outcome; there is no separate Decisions
# tab.

VERDICT_LOW = "low_risk"
VERDICT_HIGH = "high_risk"
VERDICTS = (VERDICT_LOW, VERDICT_HIGH)

# Legacy vocabulary, normalised on read. "flagged" folds up to high_risk: it
# always meant "a human needs to look at this".
LEGACY_VERDICTS = {
    "compliant": VERDICT_LOW,
    "flagged": VERDICT_HIGH,
    "low": VERDICT_LOW,
}


def normalise_verdict(value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    if key in VERDICTS:
        return key
    return LEGACY_VERDICTS.get(key, key)


ADDENDUM_B_UPLIFT = 1.15

HANDBOOK_ISSUE = "2019-03-01"
ADDENDUM_A_ISSUE = "2020-04-01"
ADDENDUM_B_ISSUE = "2022-01-01"


@dataclass(frozen=True)
class Limit:
    """basis: per_claim (default) / per_head / per_day / per_month.
    hard=False means a guideline (5.2), not a ceiling."""

    category: str
    amount: float
    basis: str
    base_period: str
    source: str
    hard: bool = True
    note: str = ""


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

# Categories the handbook sets no numeric ceiling for; fall back to the
# general approval thresholds below.
UNCAPPED_CATEGORIES = (
    "TRAVEL",
    "ACCOMMODATION",
    "TRAINING",
    "OFFICE_SUPPLIES",
    "POSTAGE_COURIER",
    "MISCELLANEOUS",
    "OTHER",
)

MEAL_LIMITS: dict[str, float] = {
    "breakfast": round(12 * ADDENDUM_B_UPLIFT, 2),
    "lunch": round(15 * ADDENDUM_B_UPLIFT, 2),
    "dinner": round(25 * ADDENDUM_B_UPLIFT, 2),
}

# Current, confirmed by Amara — not handbook figures, not inflation-adjusted.
APPROVAL_THRESHOLDS = {
    "line_manager": 250.0,
    "cfo": 2000.0,
}

# What the 2019 handbook said, kept for the "policy decay" story in the brief.
HANDBOOK_APPROVAL_THRESHOLDS = {
    "line_manager": 250.0,
    "head_of_finance": 1000.0,
}

MISC_JUSTIFICATION_THRESHOLD = 30.0
RECEIPT_REQUIRED_THRESHOLD = 25.0
SUBMISSION_WINDOW_DAYS = 30


def limit_for(category: str | None) -> Limit | None:
    if not category:
        return None
    return CATEGORY_LIMITS.get(str(category).strip().upper())


def normalise_category(category: str | None) -> str:
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
