from sheets import receipts_ws, RECEIPT_HEADERS, insert_receipt, insert_verdict
from audit import map_verdict
import pandas as pd
from flask import request
from flask import Flask
app = Flask(__name__)


@app.get("/api/expenses")
def approved_expenses():
    page = int(request.args.get("page", 1))
    page_size = min(int(request.args.get("page_size", 25)), 100)

    df = pd.DataFrame(receipts_ws().get_all_records(), columns=RECEIPT_HEADERS)
    if df.empty:
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    df = df[df["status"] == "approved"]
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
    return {"total": total, "page": page, "page_size": page_size,
            "results": page_df.assign(receipt_date=page_df["receipt_date"].dt.strftime("%Y-%m-%d")).to_dict("records")}


@app.post("/api/audit")
def audit_receipt():
    """Called by n8n's new 'Persist to Audit API' node, placed right after
    'Final Risk Assessment' — n8n has already run the governance-prompt LLM
    call and computed risk_level itself; this endpoint just persists it."""
    payload = request.get_json()
    verdict = map_verdict(payload.get("risk_level", "LOW"))

    receipt_id = insert_receipt({
        "receipt_date": payload.get("transaction_date"), "merchant": payload.get("merchant"),
        "line_items": payload.get("line_items", []), "total_amount": payload.get("total"),
        "tax": payload.get("tax"), "category": str(payload.get("category", "OTHER")).lower(),
        "currency": payload.get("currency"), "submitter": payload.get("submitted_by"),
        "status": "pending_review",
    })
    insert_verdict(receipt_id, verdict, payload.get("summary", ""))

    return {"receipt_id": receipt_id, "verdict": verdict}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(port=5000, debug=True)
