"""
Seeds the `receipts` DB with the 20 real annotated receipts (data/annotations.xml),
via dashboard/data.py's parser. Also inserts each receipt's placeholder verdict
into `verdicts` so the Review Queue can eventually read from the DB instead of
re-parsing XML. Re-runnable: truncates and reloads each time.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard.data import load_mock_receipts

CONN_PARAMS = dict(host="localhost", dbname="receipts")


def main():
    df = load_mock_receipts()

    conn = psycopg2.connect(**CONN_PARAMS)
    cur = conn.cursor()
    cur.execute("TRUNCATE decisions, verdicts, receipts RESTART IDENTITY CASCADE;")

    for _, row in df.iterrows():
        cur.execute(
            """
            INSERT INTO receipts
                (receipt_date, merchant, line_items, total_amount, category,
                 currency, submitter, raw_file_reference, source_channel, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING receipt_id;
            """,
            (
                row["date"].date() if pd.notna(row["date"]) else None,
                row["merchant"],
                json.dumps(row["line_items"]),
                row["total"],
                row["category"],
                row["currency"],
                row["submitter"],
                row["raw_file_ref"],
                row["source_channel"],
                row["status"],
            ),
        )
        receipt_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO verdicts (receipt_id, verdict, reason) VALUES (%s, %s, %s);",
            (receipt_id, row["verdict"], "placeholder rule pending C3 Governance Prompt"),
        )

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM receipts;")
    print(f"Seeded {cur.fetchone()[0]} receipts.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
