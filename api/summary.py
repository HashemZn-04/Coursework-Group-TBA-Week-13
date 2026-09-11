try:  # importable both as `api.summary` and as a sibling of `app.py`
    from api.policy import VERDICT_HIGH, VERDICT_LOW
except ImportError:  # pragma: no cover - exercised only by `python api/app.py`
    from policy import VERDICT_HIGH, VERDICT_LOW

CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}

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
    VERDICT_HIGH: "Needs your decision",
    VERDICT_LOW: "Auto-approved",
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
    described = []
    for flag in flags or []:
        if not flag:
            continue
        text = FLAG_DESCRIPTIONS.get(flag)
        if text is None:
            text = str(flag).strip()
            if not text:
                continue
        if text not in described:
            described.append(text)
    return described


def build_summary(receipt: dict, verdict: str, flags=None,
                  contextual_summary: str = "", validation: dict | None = None,
                  submitter: str | None = None) -> dict:
    receipt = receipt or {}
    merchant = str(receipt.get("merchant") or "Unknown merchant").strip()
    currency = receipt.get("currency")
    money = format_money(receipt.get("total"), currency)
    date = str(receipt.get("transaction_date") or "date not read").strip()
    category = str(receipt.get("category")
                   or "uncategorised").replace("_", " ").lower()
    who = str(submitter or receipt.get("submitter")
              or "unknown submitter").strip()
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
        if verdict == VERDICT_LOW:
            body.append("Notes: " + join_reasons(reasons) + ".")
        else:
            body.append("Flagged because it is " + join_reasons(reasons) + ".")
    elif verdict == VERDICT_LOW:
        body.append("Passed every policy check and was approved automatically. "
                    "No human review was required.")

    summary = " ".join([lead, *body])

    slack_lines = [f"*{headline}* — {money} at {merchant}",
                   f"> {category} · {who} · {date}"]
    if contextual_summary and str(contextual_summary).strip():
        slack_lines.append(str(contextual_summary).strip())
    slack_lines.extend(
        f"• {reason[0].upper()}{reason[1:]}" for reason in reasons)

    return {
        "headline": headline,
        "summary": summary,
        "slack_message": "\n".join(slack_lines),
        "reasons": reasons,
    }


def join_reasons(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return "; ".join(items[:-1]) + "; and " + items[-1]
