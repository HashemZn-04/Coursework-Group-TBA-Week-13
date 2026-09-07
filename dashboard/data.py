"""
Mock data loader for E1 (dashboard shell).

Parses data/annotations.xml (20 real hand-labeled receipts) into a DataFrame
shaped like the B3 schema. Category/submitter/verdict are NOT in the real
annotations, so they're fabricated deterministically here as placeholders
until C3 (Policy Match) and real submissions exist. Replace load_mock_receipts()
with a real DB query once C1/C6 are live.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANNOTATIONS_PATH = DATA_DIR / "annotations.xml"

_CATEGORIES = ["travel", "software", "meals", "office_supplies", "other"]
_SUBMITTERS = ["amara.osei", "j.chen", "r.patel", "l.garcia", "m.osei"]
_DATE_FORMATS = ["%m/%d/%y %H:%M:%S", "%m-%d-%Y %I:%M%p", "%m/%d/%Y", "%m-%d-%Y"]


def _parse_date(text: str) -> str:
    text = (text or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_total(text: str) -> float:
    match = re.search(r"(\d+\.\d{2})", text or "")
    return float(match.group(1)) if match else None


def _mock_verdict(total: float, category: str) -> str:
    """Placeholder rule until C3's Governance Prompt exists."""
    if total is None:
        return "flagged"
    if category == "software" or total > 500:
        return "high_risk"
    if total > 100:
        return "flagged"
    return "compliant"


def load_mock_receipts() -> pd.DataFrame:
    tree = ET.parse(ANNOTATIONS_PATH)
    root = tree.getroot()

    rows = []
    for image in root.findall("image"):
        image_id = int(image.get("id"))
        merchant, total, date, items = None, None, None, []

        for box in image.findall("box"):
            label = box.get("label")
            text_attr = box.find("attribute[@name='text']")
            text = text_attr.text if text_attr is not None else None

            if label == "shop":
                merchant = text
            elif label == "total":
                total = _parse_total(text)
            elif label == "date_time":
                date = _parse_date(text)
            elif label == "item":
                items.append({"description": text, "amount": None, "quantity": 1})

        category = _CATEGORIES[image_id % len(_CATEGORIES)]
        submitter = _SUBMITTERS[image_id % len(_SUBMITTERS)]
        verdict = _mock_verdict(total, category)
        status = "approved" if verdict == "compliant" else "pending_review"

        rows.append({
            "receipt_id": f"r-{image_id:04d}",
            "merchant": merchant or "UNKNOWN",
            "date": date,
            "category": category,
            "line_items": items,
            "total": total,
            "currency": "USD",
            "submitter": submitter,
            "source_channel": "slack",
            "raw_file_ref": image.get("name"),
            "verdict": verdict,
            "status": status,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df
