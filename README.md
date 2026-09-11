# Group Coursework: Autonomous Expense Intelligence

## Setup

```bash
git clone <repo-url>
cd Coursework-Group-TBA-Week-13
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Git LFS (large files)

Large files (currently `data_3.zip`, the SROIE2019 dataset) are stored with Git LFS, not in the repo directly.

### First time setup (macOS)

```bash
brew install git-lfs
git lfs install
```

### Pull large files after cloning

```bash
git lfs pull
```

### Extract the SROIE2019 dataset

```bash
unzip data_3.zip -d data/
```

This creates `data/SROIE2019/`. The `data/` folder also already contains `annotations.xml`, `receipts.csv`, `boxes/`, `images/`, and `tourism-recipts.csv`, tracked normally in git (not LFS).

### Tracking a new large file

```bash
git lfs track "path/to/your/file.ext"
git add .gitattributes "path/to/your/file.ext"
git commit -m "Add large asset via Git LFS"
git push origin main
```

## Data store (Google Sheets)

As of 2026-09-09 the system of record is a shared Google Sheet, not Postgres — faster to stand up for a one-week build and everyone can see the data live:
https://docs.google.com/spreadsheets/d/1avXBzepTNQXcjl4aHW7ocdLBk5KooPVMw0U1I2uZRoE/edit

It has one tab, `Receipts`, holding every field a receipt needs plus its risk
assignment (`verdict`, `verdict_reason`) and the CFO's decision timestamp
(`decided_at`) on the same row, plus a second tab, `Cluster Reviews`, holding
Amara's "I have looked at this group of claims" marks from the Patterns of
Concern page. There is no separate Verdicts/Decisions tab and no history of
re-decisions — only the latest state per receipt. `database/` (Postgres) is no
longer used and has been removed.

### One-time credentials setup

1. Create a Google Cloud service account with the Sheets + Drive APIs enabled, download its JSON key.
2. Share the sheet above with the service account's email as an **Editor**.
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and paste in the key's fields.

Full click-by-click steps: `ticket_work/epic_3_tickets.md` ("One-time setup" section).

No other credentials are needed. The audit engine's inflation source (the World
Bank's global consumer-price series) requires no API key and no signup.

## Audit engine (Flask)

```bash
source .venv/bin/activate
python api/app.py          # http://localhost:5000
```

| Endpoint | Ticket | What it does |
|---|---|---|
| `GET /health` | — | Liveness check |
| `POST /api/audit` | C3, C4, C5 | Audits one receipt: inflation-adjusted limit check, verdict, natural-language summary; writes one row to **Receipts** with `verdict`/`verdict_reason` set. A `low_risk` verdict is auto-approved on the spot (`status = approved`, `decided_at` left blank); `high_risk` goes to the review queue as `pending_review` until the CFO acts |
| `POST /api/validate` | C4 | Inflation-adjusted limit check alone, nothing persisted |
| `GET /api/expenses` | C6 | Filterable, paginated expense query (`status`, `category`, `submitter`, `start_date`, `end_date`, `min_amount`, `max_amount`, `page`, `page_size`) |
| `GET /api/receipts/<id>` | C1 | The full record for one receipt: submission, verdict and decision, all on one row |

The live pipeline does not depend on this process running — n8n writes to the
sheet through its own Google Sheets node, and the dashboard reads the sheet
directly. What this is: the tested reference implementation of the verdict logic,
the inflation maths, and the row shapes everything else has to agree on.

### CPI reference sheet (read by n8n)

n8n's AI agent tool sub-workflow reads inflation data from a Google Sheet rather
than calling the World Bank itself, so the workflow has no external dependency at
audit time and sees the same numbers this repo's tests do.

```bash
python scripts/sync_cpi.py --dry-run   # show what would be written
python scripts/sync_cpi.py             # write the CPI tab
```

Writes one row per year to a **CPI** tab: `series_id`, `year`,
`inflation_rate_pct`, `price_index`, `fetched_at`, `source`. `price_index` is
chained from the annual rates and anchored at 100, so re-pricing a limit set in
year A to year B is `index(B) / index(A)` — a lookup, not a calculation n8n has
to get right.

**Two one-time steps before the first run:**

1. Put the CPI spreadsheet's ID in `CPI_SPREADSHEET_ID` (top of `api/sheets.py`,
   or as an environment variable). Leave it unset to use a CPI tab inside the
   main expense spreadsheet.
2. Open that spreadsheet → **Share** → add the service account's `client_email`
   (from `service_account.json`) as an **Editor**. Link-sharing does not cover
   API access; without this the write fails with a 403.

Re-run it when the World Bank publishes (annually) or before a demo. C2 is the
n8n-native version of this same job.

### C4 acceptance evidence

```bash
python scripts/c4_demo.py            # five constructed examples, live World Bank data
python scripts/c4_demo.py --api http://localhost:5000   # same, through the API
```

Inflation comes from **one global series** — the World Bank's world aggregate for
annual consumer-price inflation — applied to receipts from anywhere, with no
per-country lookup and no API key. What gets re-priced is Meridian's own GBP
limit, which is the same figure wherever the expense was incurred. The trade-off:
that series is annual and published in arrears (latest full year 2025), so the
adjustment is year-granular and lags the present by about a year. Every result
reports the years it used.

Exits non-zero if any example classifies wrongly. Paste the output into MCP-27.

### Stretch-goal acceptance evidence

```bash
python scripts/h1_demo.py     # H1 — 3-month-ahead travel spend forecast
python scripts/i1_demo.py     # I1 — syndicated-spending detection
```

Same shape as `c4_demo.py`: constructed scenarios with a stated expected
outcome, exiting non-zero on any mismatch, so the output is evidence when it
passes and a failing check when it does not.

`h1_demo.py` leads with the live sheet's own shape — one travel receipt, with no
verdict — where the model **refuses by name** rather than inventing a number.
There is no travel-spend history to fit yet, and that is worth saying in the
ticket rather than hiding.

`i1_demo.py` leads with the live sheet's actual rows: seven near-identical
WAL\*MART claims dated the same day across two submitters, spelled three ways.
The remaining scenarios are QA's I3 ticket run in advance — legitimate shared
spend that must *not* be raised.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

No credentials, no network: the inflation series is stubbed and the sheet tabs
are replaced with in-memory fakes, so anyone on the team can run the suite on a
fresh clone.

`tests/test_pages.py` drives the Streamlit pages themselves through
`streamlit.testing.v1` — seed the sheet, run the page, click the button, assert
what a reviewer would actually see. That is what catches the class of bug where
the arithmetic underneath is right and the page is wrong.

## Dashboard (Streamlit)

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Pages are auto-listed from `pages/`:

| Page | Ticket | What it shows |
|---|---|---|
| Spend Overview | E2, H2 | Claimed / approved / at-risk / **prevented**, per currency; spend velocity; the running total of leakage prevented; spend by category; 3-month-ahead travel forecast |
| Review Queue | E4 | High-risk claims awaiting a decision, with the summary the submitter also got in Slack. A claim leaves the queue once it is decided |
| Expense Browser | E5 | Every claim, filterable by date, category, submitter and amount |
| Policy Health | E3 | Compliance state per month, most-broken handbook rules, breakdowns by category and submitter, and the "policy decay" count |
| Patterns of Concern | I2 | Groups of claims that look like one claim — filed twice by one person, or split across several — with the similarity basis spelled out and a "mark reviewed" that records the exact claims reviewed |

**At risk vs prevented.** These are different numbers and the Spend Overview says
so. *At risk* is money still on the table — flagged, undecided. *Prevented* is
money already stopped — rejected. Only the second is a saving; the tile used to
show the first under the second's name.

**Currency.** Totals are grouped by currency and never added across. Nothing in
this pipeline converts (Handbook 12.2 wants the rate on the transaction date and
no FX source is wired in), so a USD claim and a GBP one are reported separately
rather than summed under one symbol.

**Verdicts.** Two values: `low_risk` (approved automatically by the audit engine — never reaches a human) and `high_risk` (goes to the Review Queue for Amara's decision). Rows written before this model was adopted said `compliant`/`flagged`/`low`; those are mapped on read (`compliant`/`low`→`low_risk`, `flagged`→`high_risk`), so no sheet migration is needed. Reads and writes the single Receipts tab via `dashboard/data.py`; Review Queue's Approve/Reject buttons write the decision back to the same row (`status` + `decided_at`).

## Project structure

```
streamlit_app.py       Dashboard entry point
pages/                 Streamlit pages (auto-navigated)
dashboard/             Data loading and shared dashboard logic
  data.py              Sheet loaders, decision recording, cache contract
  spend.py             E2 — money by outcome, spend velocity, leakage prevented
  policy_health.py     E3 — compliance trend and re-checked handbook rules
  forecast_view.py     H2 — the forecast section on Spend Overview
api/                   Audit engine
  app.py               Flask endpoints (C3/C4/C5/C6)
  audit.py             C4 — global inflation lookup and limit re-pricing
  policy.py            Handbook limits, with the section and date each came from
  summary.py           C5 — the natural-language summary, for Slack and dashboard
  sheets.py            Google Sheets persistence (the single Receipts tab)
  forecast.py          H1 — 3-month-ahead travel spend regression, and its refusals
  clusters.py          I1 — syndicated-spending and duplicate-claim detection
  governance_prompt.py A3 — the system prompt n8n's audit node runs
scripts/c4_demo.py     C4 acceptance evidence, runnable
scripts/h1_demo.py     H1 acceptance evidence, runnable
scripts/i1_demo.py     I1 acceptance evidence, runnable
scripts/sync_cpi.py    Refreshes the CPI sheet n8n's agent reads
tests/                 pytest suite (no credentials or network needed)
data/                  Sample receipts, annotations, SROIE2019 dataset
discovery_docs/        Project brief, tickets, schema, and workflow docs
ticket_work/           Epic C ticket guide and session handoff
```
