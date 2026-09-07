# Receipt Schema

## Fields
- receipt id (int)(PKEY)
- merchant (txt)
- date (date) - (this is the date of the receipt)
- line items (JSON/JSONB array of each item, where each items has description, amount, and quantity)
- tax (int)
- total (int)
- currency (str)
- submitter (str)
- source channel (str)
- raw file reference (str)
- submission timestamp (timestamp)