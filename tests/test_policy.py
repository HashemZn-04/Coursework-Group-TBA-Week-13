"""Handbook limits — provenance and lookup.

These read like trivia, but they are the tests that catch someone quietly
"tidying" a figure that traces to a specific handbook section, which would make
every downstream verdict wrong in a way nothing else would notice.
"""

import pytest

from api import policy


def test_addendum_b_uplift_is_applied_to_the_2019_base_figures():
    """Addendum B (Jan 2022) uplifted subsistence and staff entertainment 15%;
    Addendum C confirmed that applies to the original 2019 figures."""
    assert policy.CATEGORY_LIMITS["SUBSISTENCE"].amount == 46.0        # £40 x 1.15
    assert policy.CATEGORY_LIMITS["STAFF_ENTERTAINMENT"].amount == 46.0
    assert policy.CATEGORY_LIMITS["SUBSISTENCE"].base_period == policy.ADDENDUM_B_ISSUE
    assert policy.MEAL_LIMITS == {"breakfast": 13.8, "lunch": 17.25, "dinner": 28.75}


def test_client_entertainment_was_deliberately_not_uplifted():
    """Addendum B skipped 5.2 on purpose, so it keeps the 2019 base — which is
    what makes it the category most likely to produce a "good deal" reading."""
    limit = policy.CATEGORY_LIMITS["CLIENT_ENTERTAINMENT"]
    assert limit.amount == 75.0
    assert limit.base_period == policy.HANDBOOK_ISSUE
    assert limit.hard is False  # 5.2 calls these guidelines, not ceilings


def test_approval_thresholds_are_amaras_current_figures_not_the_handbooks():
    """"The CFO approval used to be over a thousand. It's over two thousand
    now" — the handbook's £1,000 is stale, and both are kept so the gap is
    visible rather than silently resolved."""
    assert policy.APPROVAL_THRESHOLDS == {"line_manager": 250.0, "cfo": 2000.0}
    assert policy.HANDBOOK_APPROVAL_THRESHOLDS["head_of_finance"] == 1000.0


def test_limit_for_is_case_insensitive_and_returns_none_when_uncapped():
    assert policy.limit_for("subsistence").amount == 46.0
    assert policy.limit_for("SUBSISTENCE").amount == 46.0
    assert policy.limit_for("TRAVEL") is None
    assert policy.limit_for(None) is None


@pytest.mark.parametrize("raw,expected", [
    ("SUBSISTENCE", "SUBSISTENCE"),
    ("meals", "SUBSISTENCE"),
    ("Travel (Rail)", "OTHER"),   # unparsed punctuation stays honest
    ("travel_rail", "TRAVEL"),
    ("software", "SOFTWARE_TECHNOLOGY"),
    ("misc", "MISCELLANEOUS"),
    ("something we've never seen", "OTHER"),
    ("", "OTHER"),
    (None, "OTHER"),
])
def test_normalise_category(raw, expected):
    assert policy.normalise_category(raw) == expected


def test_every_category_the_llm_can_return_is_either_capped_or_explicitly_uncapped():
    """The audit node's JSON schema constrains the category to this enum, so any
    value it returns must resolve to a limit or to a documented "no limit" —
    never fall through to an unhandled case."""
    llm_enum = {
        "TRAVEL", "ACCOMMODATION", "SUBSISTENCE", "CLIENT_ENTERTAINMENT",
        "STAFF_ENTERTAINMENT", "SOFTWARE_TECHNOLOGY", "TRAINING",
        "OFFICE_SUPPLIES", "POSTAGE_COURIER", "PROFESSIONAL_SUBSCRIPTION",
        "MISCELLANEOUS", "OTHER",
    }
    covered = set(policy.CATEGORY_LIMITS) | set(policy.UNCAPPED_CATEGORIES)
    assert llm_enum == covered


def test_every_limit_cites_its_source_and_base_period():
    for name, limit in policy.CATEGORY_LIMITS.items():
        assert limit.source, name
        assert limit.base_period.endswith("-01"), name  # stored as a month start
        assert limit.basis in {"per_claim", "per_head", "per_day", "per_month"}, name
