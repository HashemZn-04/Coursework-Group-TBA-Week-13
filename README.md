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

## Database (PostgreSQL)

### First time setup (macOS)

```bash
brew install postgresql@17
brew services start postgresql@17
```

### Create the schema

```bash
psql -h localhost -U "$(whoami)" -d postgres -f database/setup.sql
```

This drops and recreates the `receipts` database with the `receipts`, `verdicts`, and `decisions` tables (`database/setup.sql`).

### Seed sample data

```bash
source .venv/bin/activate
python database/seed.py
```

Loads the 20 real annotated receipts from `data/annotations.xml` into the database. Re-runnable, truncates and reloads each time.

### Connect manually

```bash
psql -h localhost -U "$(whoami)" -d receipts
```

Useful queries are in `database/queries.sql`.

## Dashboard (Streamlit)

```bash
source .venv/bin/activate
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Pages (Spend Overview, Review Queue, Expense Browser) are auto-listed from `pages/`. Currently reads mock data straight from `data/annotations.xml` via `dashboard/data.py`, not yet from the Postgres database.

## Project structure

```
streamlit_app.py       Dashboard entry point
pages/                 Streamlit pages (auto-navigated)
dashboard/              Data loading and shared dashboard logic
database/               Schema (setup.sql), seed script, saved queries
data/                    Sample receipts, annotations, SROIE2019 dataset
discovery_docs/          Project brief, tickets, schema, and workflow docs
```
