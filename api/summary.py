"""
C5 — High-risk routing and natural-language summary generation (MCP-31).

Amara's bar for a one-click decision, in her own words: "a lot of the time, it
can just be a sentence." So the summary this builds leads with the four things
she needs to see before clicking — what was flagged, why, how much, and who
submitted it — and only then lists the detail. It is generated deterministically
from the audit result rather than by a second LLM call: the reasoning has
already been produced upstream by the governance prompt, and re-generating it
here would add latency, cost, and a second thing that can hallucinate to a
sentence that mostly assembles facts we already hold.

Two renderings come out of one call:

* `summary` — plain prose, stored in the Verdicts tab's `reason` column and
  shown in the Streamlit Review Queue. This is the dashboard half of the ticket.
* `slack_message` — the same content in Slack mrkdwn, returned by `/api/audit`
  so n8n's Slack node can post it verbatim instead of re-formatting it. This is
  the Slack half.

Keeping both in one place is the point: the message Amara reads in Slack and the
one she reads in the dashboard are the same sentence, from the same source.
"""

CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}

#: Deterministic flag codes -> what they mean in a sentence a human reads.
#: Keys match n8n's "Deterministic Policy Checks" node plus the two C4 adds.
FLAG_DESCRIPTIONS = {
    "EXPENSE_OUTSIDE_ONE_MONTH_CUTOFF":
        "submitted more than a month after the expense date, which policy "
        "auto-rejects with no exceptions",
    "CFO_APPROVAL_THRESHOLD":
        "at or above the £2,000 CFO approval threshold",
    "EXTRACTION_REQUIRES_REVIEW":
        "the receipt could not be read confidently, so the figures below may be "
        "wrong",
    "UNCLEAR_RECEIPT_FIELDS":
        "some fields could not be read off the receipt",
    "RECEIPT_MISSING":
        "no receipt image was attached to the claim",
    "INFLATION_ADJUSTED_LIMIT_EXCEEDED":
        "over the category limit even after adjusting that limit for inflation",
    "OVER_CATEGORY_GUIDELINE":
        "over the category's guideline figure once adjusted for inflation",
}

VERDICT_HEADLINES = {
    "high_risk": "Needs your decision",
    "flagged": "Needs an explanation from the employee",
    "compliant": "No action needed",
}


def format_money(amount, currency: str | None = None) -> str:
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    code = (currency or "").strip().upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {code}".strip()


def describe_flags(flags) -> list[str]:
    """Deterministic codes become sentences; LLM risk factors pass through."""
    described = []
    for flag in flags or []:
        if not flag:
            continue
        text = FLAG_DESCRIPTIONS.get(flag)
        if text is None:
            # An LLM-produced risk factor — already free text, keep it verbatim
            # rather than guessing at a rewrite.
            text = str(flag).strip()
            if not text:
                continue
        if text not in described:
            described.append(text)
    return described


def build_summary(receipt: dict, verdict: str, flags=None,
                  contextual_summary: str = "", validation: dict | None = None,
                  submitter: str | None = None) -> dict:
    """Assemble the reviewer-facing summary for one audited receipt.

    `receipt` is the audit engine's receipt object (merchant, transaction_date,
    total, currency, category). `contextual_summary` is the governance prompt's
    own one-liner from n8n; it leads the "why" when present, because it is the
    part that reasons about *this* expense rather than about the rules.
    """
    receipt = receipt or {}
    merchant = str(receipt.get("merchant") or "Unknown merchant").strip()
    currency = receipt.get("currency")
    money = format_money(receipt.get("total"), currency)
    date = str(receipt.get("transaction_date") or "date not read").strip()
    category = str(receipt.get("category") or "uncategorised").replace("_", " ").lower()
    who = str(submitter or receipt.get("submitter") or "unknown submitter").strip()
    headline = VERDICT_HEADLINES.get(verdict, "Needs review")

    reasons = describe_flags(flags)
    validation = validation or {}
    detail = validation.get("detail")
    if detail and validation.get("assessment") != "NO_LIMIT":
        reasons.append(detail)

    lead = f"{headline}: {money} at {merchant} ({category}), submitted by {who}, dated {date}."

    body = []
    if contextual_summary and str(contextual_summary).strip():
        body.append(str(contextual_summary).strip())
    if reasons:
        if verdict == "compliant":
            body.append("Notes: " + _join(reasons) + ".")
        else:
            body.append("Flagged because it is " + _join(reasons) + ".")
    elif verdict == "compliant":
        body.append("Passed every policy check with nothing outstanding.")

    summary = " ".join([lead, *body])

    slack_lines = [f"*{headline}* — {money} at {merchant}",
                   f"> {category} · {who} · {date}"]
    if contextual_summary and str(contextual_summary).strip():
        slack_lines.append(str(contextual_summary).strip())
    slack_lines.extend(f"• {reason[0].upper()}{reason[1:]}" for reason in reasons)

    return {
        "headline": headline,
        "summary": summary,
        "slack_message": "\n".join(slack_lines),
        "reasons": reasons,
    }


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return "; ".join(items[:-1]) + "; and " + items[-1]
