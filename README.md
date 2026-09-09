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

It has three tabs — `Receipts`, `Verdicts`, `Decisions` — mirroring the original `database/` schema field-for-field. `database/setup.sql`, `database/seed.py`, and `database/queries.sql` are kept for reference but are no longer used.

### One-time credentials setup

1. Create a Google Cloud service account with the Sheets + Drive APIs enabled, download its JSON key.
2. Share the sheet above with the service account's email as an **Editor**.
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and paste in the key's fields.

Full click-by-click steps: `ticket_work/epic_3_tickets.md` ("One-time setup" section).

4. Copy `.env.example` to `.env` and add a free FRED API key (used by the audit
   engine's inflation adjustment). Optional — without it the engine falls back to
   a pinned CPI snapshot and says so in every result.

## Audit engine (Flask)

```bash
source .venv/bin/activate
python api/app.py          # http://localhost:5000
```

| Endpoint | Ticket | What it does |
|---|---|---|
| `GET /health` | — | Liveness check |
| `POST /api/audit` | C3, C4, C5 | Audits one receipt: inflation-adjusted limit check, verdict, natural-language summary; writes a row to **Receipts** and one to **Verdicts** |
| `POST /api/validate` | C4 | Inflation-adjusted limit check alone, nothing persisted |
| `GET /api/expenses` | C6 | Filterable, paginated expense query (`status`, `category`, `submitter`, `start_date`, `end_date`, `min_amount`, `max_amount`, `page`, `page_size`) |
| `GET /api/receipts/<id>` | C1 | Full paper trail for one receipt: submission, verdicts, decisions |

The live pipeline does not depend on this process running — n8n writes to the
sheet through its own Google Sheets node, and the dashboard reads the sheet
directly. What this is: the tested reference implementation of the verdict logic,
the inflation maths, and the row shapes everything else has to agree on.

### C4 acceptance evidence

```bash
python scripts/c4_demo.py            # five constructed examples, live CPI
python scripts/c4_demo.py --api http://localhost:5000   # same, through the API
```

Exits non-zero if any example classifies wrongly. Paste the output into MCP-27.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

No credentials, no network: FRED is stubbed and the three sheet tabs are replaced
with in-memory fakes, so anyone on the team can run the suite on a fresh clone.

## Dashboard (Streamlit)

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Pages (Spend Overview, Review Queue, Expense Browser) are auto-listed from `pages/`. Reads and writes the Google Sheet above via `dashboard/data.py`; Review Queue's Approve/Reject buttons write real decisions back to the sheet.

## Project structure

```
streamlit_app.py       Dashboard entry point
pages/                 Streamlit pages (auto-navigated)
dashboard/             Data loading and shared dashboard logic
api/                   Audit engine
  app.py               Flask endpoints (C3/C4/C5/C6)
  audit.py             C4 — CPI lookup and inflation-adjusted limit comparison
  policy.py            Handbook limits, with the section and date each came from
  summary.py           C5 — the natural-language summary, for Slack and dashboard
  sheets.py            Google Sheets persistence (C1's three tabs)
  governance_prompt.py A3 — the system prompt n8n's audit node runs
scripts/c4_demo.py     C4 acceptance evidence, runnable
tests/                 pytest suite (no credentials or network needed)
database/              Legacy Postgres schema, seed script, saved queries
data/                  Sample receipts, annotations, SROIE2019 dataset
discovery_docs/        Project brief, tickets, schema, and workflow docs
ticket_work/           Epic C ticket guide and session handoff
```
