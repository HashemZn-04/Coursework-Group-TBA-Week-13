"""
The audit engine's HTTP surface — C3 persistence, C4 validation, C5 summary
generation, and C6's query API.

Run it with `python api/app.py` (or `flask --app api.app run`), both of which the
import shim below supports.

A note on where this sits in the live system, because it is easy to
misread: `dashboard/data.py` reads the Google Sheet directly, so the Streamlit
dashboard does not depend on this process being up, and n8n writes to the sheet
through its own native Google Sheets node rather than calling here (a localhost
Flask app is not reachable from n8n Cloud, and this project has no hosting
target for one). What this module *is*: the executable, tested specification of
what the pipeline must produce — the exact verdict logic, the exact inflation
maths, the exact summary wording, and the exact row shape the sheet expects.
Point n8n's audit branch at `/api/audit` behind a tunnel and the whole pipeline
runs through it unchanged; leave it off and the numbers here are still the
reference QA (C7) checks n8n's own nodes against.
"""

import pandas as pd
from flask import Flask, request

try:  # importable both as `api.app` and as `python api/app.py`
    from api.audit import contextual_validation, final_verdict, map_verdict
    from api.policy import normalise_category
    from api.sheets import (RECEIPT_HEADERS, audit_trail, insert_receipt,
                            insert_verdict, receipts_ws, record_cpi_snapshot)
    from api.summary import build_summary
except ImportError:  # pragma: no cover - exercised only by `python api/app.py`
    from audit import contextual_validation, final_verdict, map_verdict
    from policy import normalise_category
    from sheets import (RECEIPT_HEADERS, audit_trail, insert_receipt,
                        insert_verdict, receipts_ws, record_cpi_snapshot)
    from summary import build_summary

app = Flask(__name__)

#: CPI provenance is written to the Benchmarks tab once per process, not once
#: per request — the index only moves monthly, and a Sheets round-trip per audit
#: would put a live demo over Amara's "a few seconds" latency bar.
_cpi_recorded: set[tuple[str, str]] = set()


@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# C3 / C4 / C5 — audit one receipt and persist the verdict
# --------------------------------------------------------------------------- #

@app.post("/api/audit")
def audit_receipt():
    """Audit and persist one receipt.

    Accepts what n8n's audit branch already holds, in either of two shapes:

    * the flat shape (`merchant`, `total`, `risk_level`, `summary`, ...), which
      is what a "Persist to Audit API" HTTP node placed after "Final Risk
      Assessment" sends; or
    * the nested shape (`audit_engine_input` / `contextual_audit` /
      `final_audit_result`), which is the workflow's own internal payload.

    If the caller supplies a `risk_level`, it is trusted — n8n has already run
    the governance prompt and computed it. If not, `final_verdict()` recomputes
    it here from the deterministic checks and the contextual audit, so a caller
    that only has the raw LLM output still gets a verdict.

    Either way C4 runs on the receipt (inflation-adjusted limit comparison) and
    C5 builds the summary, and both are folded into the single `reason` string
    stored against the verdict — verdicts stay `compliant` / `flagged` /
    `high_risk`, and "good deal" or "policy violation" is reasoning, not a
    fourth verdict value.
    """
    payload = request.get_json(silent=True) or {}
    engine_input = payload.get("audit_engine_input") or {}
    contextual = payload.get("contextual_audit") or {}
    final = payload.get("final_audit_result") or {}
    policy_checks = (engine_input.get("policy_checks")
                     or payload.get("policy_checks") or {})

    receipt = dict(engine_input.get("receipt") or {})
    # Flat-shape fallbacks: read each receipt field from the top level when the
    # nested object did not carry it.
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
    _record_cpi_once(validation)

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
        "status": "pending_review",
    })
    verdict_id = insert_verdict(receipt_id, verdict, summary["summary"])

    return {
        "receipt_id": receipt_id,
        "verdict_id": verdict_id,
        "verdict": verdict,
        "risk_level": risk_level,
        "flags": flags,
        "contextual_validation": validation,
        "summary": summary["summary"],
        "slack_message": summary["slack_message"],
    }


def _record_cpi_once(validation: dict) -> None:
    cpi = validation.get("cpi")
    if not cpi:
        return
    key = (cpi["series_id"], cpi["base_period"])
    if key in _cpi_recorded:
        return
    _cpi_recorded.add(key)
    record_cpi_snapshot(cpi)


@app.post("/api/validate")
def validate_only():
    """C4 on its own, with nothing persisted.

    This is the endpoint the constructed example in the C4 acceptance criterion
    is demonstrated against (see `scripts/c4_demo.py`), and the one QA can poke
    at while spot-checking verdicts without writing rows into the shared sheet.
    """
    payload = request.get_json(silent=True) or {}
    return contextual_validation(
        payload.get("total"), payload.get("category"),
        units=payload.get("attendee_count") or payload.get("units") or 1,
        currency=payload.get("currency"))


# --------------------------------------------------------------------------- #
# C6 — query API for the dashboard
# --------------------------------------------------------------------------- #

@app.get("/api/expenses")
def approved_expenses():
    """Filterable, paginated expense query.

    Defaults to approved expenses, which is the brief's "all approved expenses
    queryable"; pass `status=` to widen it (`status=all` for everything), which
    is what QA needs when sampling verdicts across the queue.
    """
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("page_size", 25)), 1), 100)

    df = pd.DataFrame(receipts_ws().get_all_records(), columns=RECEIPT_HEADERS)
    if df.empty:
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    status = request.args.get("status", "approved")
    if status != "all":
        df = df[df["status"] == status]
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["receipt_date"] = pd.to_datetime(df["receipt_date"], errors="coerce")

    if request.args.get("start_date"):
        df = df[df["receipt_date"] >= pd.Timestamp(request.args["start_date"])]
    if request.args.get("end_date"):
        df = df[df["receipt_date"] <= pd.Timestamp(request.args["end_date"])]
    if request.args.get("category"):
        df = df[df["category"] == request.args["category"]]
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
    """Full paper trail for one receipt — submission, verdicts, decisions."""
    trail = audit_trail(receipt_id)
    if trail is None:
        return {"error": f"no receipt with id {receipt_id}"}, 404
    return trail


if __name__ == "__main__":
    app.run(port=5000, debug=True)
