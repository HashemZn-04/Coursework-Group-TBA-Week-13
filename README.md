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
dashboard/              Data loading and shared dashboard logic
database/               Schema (setup.sql), seed script, saved queries
data/                    Sample receipts, annotations, SROIE2019 dataset
discovery_docs/          Project brief, tickets, schema, and workflow docs
```
