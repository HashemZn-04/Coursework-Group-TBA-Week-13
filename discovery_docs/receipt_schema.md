## What the schema looks like in JSON
```json
  {
    "receipt_id": "r-0001",
    "submitted_at": "2026-09-07T22:14:00Z",
    "submitter": "hashem.znati@example.com",
    "source_channel": "slack",
    "merchant": "WALMART",
    "date": "2010-08-20",
    "category": "office_supplies",
    "line_items": [
      { "description": "FRAP", "amount": 5.48, "quantity": 1 },
      { "description": "BANANAS", "amount": 0.20, "quantity": 0.41 }
    ],
    "tax": 0.00,
    "total": 5.11,
    "currency": "USD",
    "raw_file_ref": "images/0.jpg",
    "status": "pending_review"
  }
```