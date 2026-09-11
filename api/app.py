import re

import pandas as pd
from flask import Flask, request

try:  # importable both as `api.app` and as `python api/app.py`
    from api.audit import contextual_validation, final_verdict, map_verdict
    from api.policy import VERDICT_LOW, normalise_category
    from api.sheets import RECEIPT_HEADERS, audit_trail, insert_receipt, receipts_ws
    from api.summary import build_summary
except ImportError:  # pragma: no cover - exercised only by `python api/app.py`
    from audit import contextual_validation, final_verdict, map_verdict
    from policy import VERDICT_LOW, normalise_category
    from sheets import RECEIPT_HEADERS, audit_trail, insert_receipt, receipts_ws
    from summary import build_summary

app = Flask(__name__)

# ISO dates must not be parsed with dayfirst=True — see parse_receipt_dates.
_ISO_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse_receipt_dates(values: pd.Series) -> pd.Series:
    values = pd.Series(values)
    is_iso = values.astype("string").str.match(_ISO_LIKE).fillna(False)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if is_iso.any():
        parsed.loc[is_iso] = pd.to_datetime(
            values[is_iso], format="mixed", errors="coerce")
    if (~is_iso).any():
        parsed.loc[~is_iso] = pd.to_datetime(
            values[~is_iso], format="mixed", dayfirst=True, errors="coerce")
    return parsed


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/audit")
def audit_receipt():
    payload = request.get_json(silent=True) or {}
    engine_input = payload.get("audit_engine_input") or {}
    contextual = payload.get("contextual_audit") or {}
    final = payload.get("final_audit_result") or {}
    policy_checks = (engine_input.get("policy_checks")
                     or payload.get("policy_checks") or {})

    receipt = dict(engine_input.get("receipt") or {})
    for field, source in (("merchant", "merchant"),
                          ("transaction_date", "transaction_date"),
                          ("total", "total"), ("tax", "tax"),
                          ("currency", "currency"), ("line_items", "line_items")):
        if receipt.get(field) in (None, "") and source in payload:
            receipt[field] = payload[source]
    receipt.setdefault("transaction_date", payload.get("receipt_date"))

    category = normalise_category(
        final.get("category") or contextual.get("category")
        or payload.get("category") or receipt.get("category"))
    receipt["category"] = category
    submitter = (engine_input.get("submitted_by") or payload.get("submitted_by")
                 or payload.get("submitter") or "")

    validation = contextual_validation(
        receipt.get("total"), category,
        units=payload.get("attendee_count") or payload.get("units") or 1,
        currency=receipt.get("currency"))

    risk_level = payload.get("risk_level") or final.get("risk_level")
    if risk_level:
        verdict = map_verdict(risk_level)
        flags = list(final.get("combined_flags")
                     or policy_checks.get("flags") or [])
        if validation.get("assessment") == "POLICY_VIOLATION":
            flags.append("INFLATION_ADJUSTED_LIMIT_EXCEEDED")
        elif validation.get("assessment") == "OVER_GUIDELINE":
            flags.append("OVER_CATEGORY_GUIDELINE")
        flags = list(dict.fromkeys(flags))
    else:
        verdict, risk_level, flags = final_verdict(
            policy_checks, contextual, validation)

    summary = build_summary(
        receipt, verdict, flags=flags,
        contextual_summary=(final.get("contextual_summary")
                            or contextual.get("summary")
                            or payload.get("summary") or ""),
        validation=validation, submitter=submitter)

    auto_approved = verdict == VERDICT_LOW
    receipt_id = insert_receipt({
        "receipt_date": receipt.get("transaction_date"),
        "merchant": receipt.get("merchant"),
        "line_items": receipt.get("line_items") or [],
        "total_amount": receipt.get("total"),
        "tax": receipt.get("tax"),
        "category": category.lower(),
        "currency": receipt.get("currency"),
        "submitter": submitter,
        "raw_file_reference": (receipt.get("file_name")
                               or payload.get("raw_file_reference") or ""),
        "status": "approved" if auto_approved else "pending_review",
        "verdict": verdict,
        "verdict_reason": summary["summary"],
    })

    return {
        "receipt_id": receipt_id,
        "verdict": verdict,
        "risk_level": risk_level,
        "auto_approved": auto_approved,
        "needs_review": not auto_approved,
        "flags": flags,
        "contextual_validation": validation,
        "summary": summary["summary"],
        "slack_message": summary["slack_message"],
    }


@app.post("/api/validate")
def validate_only():
    payload = request.get_json(silent=True) or {}
    return contextual_validation(
        payload.get("total"), payload.get("category"),
        units=payload.get("attendee_count") or payload.get("units") or 1,
        currency=payload.get("currency"))


@app.get("/api/expenses")
def approved_expenses():
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("page_size", 25)), 1), 100)

    df = pd.DataFrame(receipts_ws().get_all_records(expected_headers=RECEIPT_HEADERS),
                      columns=RECEIPT_HEADERS)
    if df.empty:
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    status = request.args.get("status", "approved")
    if status != "all":
        df = df[df["status"] == status]
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_date"] = parse_receipt_dates(df["receipt_date"])

    if request.args.get("start_date"):
        df = df[df["receipt_date"] >= pd.Timestamp(request.args["start_date"])]
    if request.args.get("end_date"):
        df = df[df["receipt_date"] <= pd.Timestamp(request.args["end_date"])]
    if request.args.get("category"):
        # Normalised on both sides — the sheet holds `Travel` from n8n and
        # `travel` from this engine, and an exact match on the raw column
        # would silently miss half of one category depending on the query's
        # own casing.
        df = df[df["category"].map(normalise_category)
               == normalise_category(request.args["category"])]
    if request.args.get("submitter"):
        df = df[df["submitter"] == request.args["submitter"]]
    if request.args.get("min_amount"):
        df = df[df["total_amount"] >= float(request.args["min_amount"])]
    if request.args.get("max_amount"):
        df = df[df["total_amount"] <= float(request.args["max_amount"])]

    total = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start:start + page_size]
    results = page_df.assign(
        receipt_date=page_df["receipt_date"].dt.strftime("%Y-%m-%d")
    ).to_dict("records")
    return {"total": total, "page": page, "page_size": page_size,
            "results": results}


@app.get("/api/receipts/<int:receipt_id>")
def receipt_audit_trail(receipt_id: int):
    trail = audit_trail(receipt_id)
    if trail is None:
        return {"error": f"no receipt with id {receipt_id}"}, 404
    return trail


if __name__ == "__main__":
    app.run(port=5000, debug=True)
