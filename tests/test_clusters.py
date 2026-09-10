"""I1 — syndicated spending and duplicate claims.

The tests that matter most here are the ones that make sure it **does not** fire:
QA's I3 ticket is specifically about constructing "legitimate shared spend
patterns" and confirming they are not flagged as fraud, and a page that cries
wolf on two colleagues buying coffee is worth less than no page at all.

The headline case is real data, not constructed: the live sheet holds seven
near-identical WAL*MART claims dated the same day across two Slack submitters,
spelled `WAL*MART`, `WAL-MART` and `Walmart`.
"""

import pandas as pd

from api.clusters import (DUPLICATE, IMMATERIAL, REVIEW, SYNDICATED,
                          find_patterns, merchant_key, pattern_identity)
from tests.conftest import expenses

LIVE_WALMART = [
    {"receipt_id": 2, "merchant": "WAL*MART", "total_amount": 5.11,
     "receipt_date": "08/20/10 13:12:01", "currency": "USD",
     "submitter": "U0B4SSV8YJE"},
    {"receipt_id": 3, "merchant": "WAL*MART", "total_amount": 5.11,
     "receipt_date": "08/20/10 13:12:01", "currency": "USD",
     "submitter": "U0B4SSV8YJE"},
    {"receipt_id": 4, "merchant": "WAL-MART", "total_amount": 5.11,
     "receipt_date": "08/20/10 13:12:01", "currency": "USD",
     "submitter": "U0B5M5WBV16"},
    {"receipt_id": 5, "merchant": "Walmart", "total_amount": 5.11,
     "receipt_date": "08/20/10 13:12:01", "currency": "USD",
     "submitter": "U0B5M5WBV16"},
]


# --------------------------------------------------------------------------- #
# Merchant normalisation — the thing that has to be right first
# --------------------------------------------------------------------------- #

def test_the_live_spellings_of_one_shop_reduce_to_one_key():
    keys = {merchant_key(name) for name in
            ("WAL*MART", "WAL-MART", "Walmart", "WAL-MART STORE #5260",
             "WAL*MART SUPERCENTER")}
    assert keys == {"WALMART"}


def test_a_merchant_that_reduces_to_nothing_matches_nothing():
    """An unreadable merchant grouping with every other unreadable merchant is
    the fastest way to make this page worthless."""
    df = expenses(*[{"receipt_id": i, "merchant": name, "total_amount": 100.0,
                     "submitter": f"u.{i}"}
                    for i, name in enumerate(["", "The Ltd", "  ", "Co"], start=1)])
    assert find_patterns(df) == []


def test_a_number_in_the_name_is_kept_but_a_branch_number_is_not():
    """Dropping every digit would fold `Cafe 22` and `Cafe 55` into one
    merchant. Keeping every digit would split a chain across its branches. So a
    `#`-prefixed branch number goes and the rest stays."""
    assert merchant_key("Cafe 22") != merchant_key("Cafe 55")
    assert merchant_key("WAL-MART STORE #5260") == merchant_key("WAL*MART")


def test_two_different_numbered_shops_are_not_treated_as_one_merchant():
    df = expenses({"receipt_id": 1, "merchant": "Cafe 22", "total_amount": 100.0,
                   "submitter": "u.one"},
                  {"receipt_id": 2, "merchant": "Cafe 55", "total_amount": 100.0,
                   "submitter": "u.two"})
    assert find_patterns(df) == []


# --------------------------------------------------------------------------- #
# The live case
# --------------------------------------------------------------------------- #

def test_the_live_walmart_claims_group_across_both_submitters():
    patterns = find_patterns(expenses(*LIVE_WALMART))

    assert len(patterns) == 1
    found = patterns[0]
    assert found.pattern == SYNDICATED
    assert found.receipts == 4
    assert found.submitters == ("U0B4SSV8YJE", "U0B5M5WBV16")
    assert found.receipt_ids == (2, 3, 4, 5)


def test_the_same_person_claiming_the_same_thing_twice_is_named_explicitly():
    """Amara's own duplicate method: "a way to look back at other ones
    submitted by the same person"."""
    found = find_patterns(expenses(*LIVE_WALMART))[0]
    assert found.exact_repeats == {"U0B4SSV8YJE": 2, "U0B5M5WBV16": 2}


def test_an_exact_repeat_is_worth_review_however_small_the_amount():
    """$5.11 is under every materiality threshold in the handbook, but filing
    the identical claim twice is a problem at any value."""
    found = find_patterns(expenses(*LIVE_WALMART))[0]
    assert found.severity == REVIEW
    assert "filed more than once by the same person" in found.basis


def test_one_submitter_repeating_a_claim_is_a_duplicate_not_a_syndicate():
    rows = [dict(row, submitter="U0B4SSV8YJE") for row in LIVE_WALMART]
    assert find_patterns(expenses(*rows))[0].pattern == DUPLICATE


def test_a_non_gbp_group_says_so_rather_than_pretending_the_thresholds_hold():
    found = find_patterns(expenses(*LIVE_WALMART))[0]
    assert found.unconverted_currency
    assert "Handbook 12.2" in found.basis


def test_the_basis_names_the_merchant_the_amounts_the_dates_and_the_people():
    """The acceptance criterion asks for a *documented* similarity basis: a
    reviewer has to be able to see why these claims were put together."""
    basis = find_patterns(expenses(*LIVE_WALMART))[0].basis
    for fragment in ("WAL*MART", "5.11", "2010-08-20", "2 submitter"):
        assert fragment in basis


# --------------------------------------------------------------------------- #
# I3's attack — legitimate shared spend must not be flagged
# --------------------------------------------------------------------------- #

def test_two_colleagues_buying_lunch_on_the_same_day_is_not_raised_for_review():
    """The commonest legitimate pattern in any office. It groups — the claims
    genuinely are similar — but nothing about it is worth Amara's time, so it
    is reported below the materiality floor rather than in the queue."""
    df = expenses({"receipt_id": 1, "merchant": "Pret A Manger",
                   "total_amount": 2.80, "receipt_date": "2026-08-03",
                   "submitter": "u.one"},
                  {"receipt_id": 2, "merchant": "Pret-A-Manger",
                   "total_amount": 3.10, "receipt_date": "2026-08-03",
                   "submitter": "u.two"})
    patterns = find_patterns(df)

    assert len(patterns) == 1
    assert patterns[0].severity == IMMATERIAL
    assert "Not raised" in patterns[0].basis


def test_a_team_using_one_approved_vendor_month_after_month_does_not_group():
    """Handbook 10.2's concern is claims clustering "on the same date". Claims
    months apart are a supplier relationship, not a split bill."""
    df = expenses(*[{"receipt_id": i, "merchant": "Regus Serviced Offices",
                     "total_amount": 300.0, "receipt_date": f"2026-0{i}-05",
                     "submitter": f"u.{i}"} for i in range(1, 6)])
    assert find_patterns(df) == []


def test_claims_of_genuinely_different_sizes_do_not_group():
    df = expenses({"receipt_id": 1, "merchant": "Hilton Manchester",
                   "total_amount": 100.0, "receipt_date": "2026-08-03",
                   "submitter": "u.one"},
                  {"receipt_id": 2, "merchant": "Hilton Manchester",
                   "total_amount": 450.0, "receipt_date": "2026-08-03",
                   "submitter": "u.two"})
    assert find_patterns(df) == []


def test_one_person_claiming_once_is_never_a_pattern():
    df = expenses({"merchant": "Hilton Manchester", "total_amount": 300.0})
    assert find_patterns(df) == []


# --------------------------------------------------------------------------- #
# Materiality, ordering, and degenerate input
# --------------------------------------------------------------------------- #

def test_a_group_reaching_the_approval_threshold_is_raised_for_review():
    """Handbook 9.2: a series of related expenses that together exceed a
    threshold "should be aggregated for approval purposes" — the provision that
    "exists principally to deter [...] split-receipting"."""
    df = expenses(*[{"receipt_id": i, "merchant": "Hawksmoor Restaurant",
                     "total_amount": 140.0, "receipt_date": "2026-08-03",
                     "submitter": f"u.{i}"} for i in range(1, 4)])
    found = find_patterns(df)[0]

    assert found.severity == REVIEW
    assert found.total == 420.0
    assert "line-manager approval threshold" in found.basis


def test_review_worthy_groups_are_ordered_ahead_of_immaterial_ones():
    df = expenses(
        *([{"receipt_id": i, "merchant": "Pret A Manger", "total_amount": 3.00,
            "receipt_date": "2026-08-03", "submitter": f"u.{i}"}
           for i in (1, 2)]
          + [{"receipt_id": i, "merchant": "Hawksmoor Restaurant",
              "total_amount": 140.0, "receipt_date": "2026-08-03",
              "submitter": f"u.{i}"} for i in (3, 4)]))
    assert [p.severity for p in find_patterns(df)] == [REVIEW, IMMATERIAL]


def test_a_claim_with_no_readable_date_or_amount_is_simply_not_grouped():
    df = expenses({"receipt_id": 1, "merchant": "Hilton Manchester",
                   "total_amount": 300.0, "receipt_date": "not a date",
                   "submitter": "u.one"},
                  {"receipt_id": 2, "merchant": "Hilton Manchester",
                   "total_amount": "not a number", "submitter": "u.two"})
    assert find_patterns(df) == []


def test_an_empty_frame_produces_no_patterns_rather_than_an_error():
    assert find_patterns(pd.DataFrame()) == []


def test_a_review_is_keyed_to_the_exact_set_of_claims_that_was_reviewed():
    """If the group later gains a claim the key changes and it comes back
    unreviewed — correct, because Amara cleared a different set."""
    assert pattern_identity((5, 2, 3)) == "2,3,5"
    assert pattern_identity((2, 3, 5)) != pattern_identity((2, 3, 5, 9))
