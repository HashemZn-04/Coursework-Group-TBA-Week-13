# Handoff 2 — Epic C build-out, CPI rework, and the verdict-model change

Covers one working session (2026-09-09). Companion docs: `ticket_work/handoff.md`
(the earlier session's narrative, since extended with per-session sections) and
`ticket_work/epic_3_tickets.md` (the living ticket-by-ticket guide — the thing to
actually work from).

**State at the end of this session:** `pytest -q` → **104 tests, green**, no
credentials or network needed. Everything DA-owned in Epic C is written and
tested. Nothing is committed — the work is uncommitted in the working tree.

---

## 1. What was asked for

Implement everything left on Epic C. Then, in sequence, the scope shifted three
times as decisions landed mid-session:

1. Build out C4 and C5 (and finish C3/C6's DA half).
2. Collapse the verdict model from three tiers to two.
3. Replace per-country CPI with a single global inflation series, and land it in
   a Google Sheet that n8n's agent tool sub-workflow reads.

Each of those is below with the reasoning, because several forced decisions that
were not specified and that someone may want to overturn.

---

## 2. Epic C — what got built

| Ticket | Status | Where |
|---|---|---|
| C1 schema | Done | 3 sheet tabs + `GET /api/receipts/<id>` reconstructs the full trail |
| C3 policy match | DA half done; **blocked** on AA's n8n fixes | `api/app.py`, `api/governance_prompt.py` |
| C4 contextual validation | **Done**, verified against live data | `api/policy.py`, `api/audit.py`, `scripts/c4_demo.py` |
| C5 routing + summary | DA half done; **blocked** on C3 | `api/summary.py`, `pages/2_Review_Queue.py` |
| C6 query API | Done | `api/app.py` |

New files: `api/policy.py`, `api/summary.py`, `scripts/c4_demo.py`,
`scripts/sync_cpi.py`, `tests/` (7 files), `.env.example`.

**C4** re-prices each handbook limit from the period it was actually set in.
Every figure in `api/policy.py` traces to a handbook section or an addendum —
Addendum B's 15% uplift applied to subsistence and staff entertainment, and
deliberately *not* to client entertainment, which is why £75/head is the stalest
live figure in the book and the best demo case.

**C5** produces one summary in two renderings (prose for the sheet and dashboard,
mrkdwn for Slack) from the same facts, so the two surfaces cannot disagree. No
second LLM call — the reasoning already exists upstream.

**C3's DA half** accepts both n8n payload shapes, trusts n8n's `risk_level` when
sent, and writes both a Receipts and a Verdicts row with a real numeric id. The
test payloads are copied out of the workflow export's node code, so the API
cannot silently drift from what n8n actually holds.

---

## 3. The verdict model changed: three tiers → two

`compliant` / `flagged` / `high_risk` became **`low`** and **`high_risk`**.
`low` is approved by the engine and never reaches a human; `high_risk` is the
review queue.

### Two decisions this forced that were not specified

1. **n8n's MEDIUM maps to `high_risk`, not `low`.** MEDIUM was the "needs an
   explanation from the employee" tier. With no middle bucket it has to fold one
   way, and folding it down would auto-approve precisely the expenses the engine
   was not confident about. Unknown risk levels default to `high_risk` for the
   same reason. n8n keeps emitting three levels — its three Slack replies need
   the distinction — only the stored verdict collapses.
2. **`low` changes state, not just labelling.** "Auto-approved" is meaningless
   unless the receipt becomes approved, so `/api/audit` writes `status =
   approved` *and* a Decisions row attributed to `ai_audit_engine`. An approved
   receipt with no decision row would be an approval with nobody behind it —
   exactly the hole C1 exists to close, and the first thing QA's D4 walk would
   find.

### The terminal-state invariant

Deterministic checks → CPI validation → final risk assessment → `low` or
`high_risk`. **There is no third outcome and no parked state.** A receipt holding
neither verdict never completed the pipeline: that is a processing failure, not a
classification, and both dashboard pages now report it in red rather than as a
footnote. `tests/test_audit.py` exhausts 480 combinations of policy checks,
contextual audit and C4 assessment to prove no input can produce anything else.

### Migration

None needed. `normalise_verdict()` maps legacy rows on read: `compliant` → `low`,
`flagged` → **`high_risk`** (folding up, same reasoning as MEDIUM). The one live
`compliant` row in the sheet already reads as `low`.

---

## 4. CPI: three sources evaluated, global chosen

The original code used FRED's US series as a proxy for GBP limits. That was
challenged, and the investigation changed the answer twice.

| Source | Verdict |
|---|---|
| FRED UK series | **Unusable.** All 40 UK CPI series on FRED are stale, freshest 2025-03 — FRED sources UK data from the OECD, which stopped publishing them. |
| UK ONS `D7BT` | **Works.** Monthly, current to 2026-07, no key. The most accurate option for GBP limits. |
| World Bank world aggregate | **Chosen.** `FP.CPI.TOTL.ZG`, country `WLD`. No key, one series for everywhere. |
| IMF DataMapper | Would cover 2026 including projections, but returns 403 to this environment. |

**Why global is right, not merely simpler:** C4 re-prices Meridian's own firm-wide
GBP limit, not the local price of the thing bought. A £75-a-head limit is £75 a
head whether the dinner was in Berlin or Bristol, so one inflation number is the
correct shape for the question. Per-country CPI was solving a problem the design
does not have.

**What it costs, and this matters before the demo:** the global series is annual
and published in arrears — latest full year **2025**, where ONS runs monthly to
2026-07. The brief asks for "2026 economic data"; this is 2025 data, year-granular,
lagging about a year. It under-states rather than over-states the re-pricing, so
it errs toward flagging. Every result reports the years it used. If recency gets
challenged, ONS `D7BT` is the fallback — at the cost of reintroducing the
per-country choice.

**Gained:** `FRED_API_KEY` is gone from the project entirely. One fewer credential
in a repo that has already had two leaks. There is now **no API key of any kind**
beyond the Google service account.

### Numbers

| Limit | was (US CPI) | now (global) |
|---|---|---|
| Client entertainment £75/head (2019) | £98.16 | £98.11 |
| Subsistence £46/day (2022) | £54.18 | £55.83 |

The C4 acceptance example is unaffected: an £88/head client dinner still
classifies `GOOD_DEAL`.

---

## 5. The CPI sheet n8n reads

n8n's agent tool sub-workflow reads inflation from a sheet rather than calling the
World Bank itself — no external dependency at audit time, and the agent and this
repo are guaranteed to see the same numbers.

* **Sheet:** https://docs.google.com/spreadsheets/d/1KQm1Zt9FncSInMHl6aPBY-2UfHGoiMvQ043DgRhWfow/edit
* **Tab:** `CPI Benchmark` (the tab that already existed — matched exactly so the
  sync writes into it rather than creating a near-duplicate `CPI` tab)
* **Id lives in one place:** `CPI_SPREADSHEET_ID` at the top of `api/sheets.py`.
  `scripts/sync_cpi.py` reads it from there rather than restating it, so there is
  one value to change instead of several that can disagree about which sheet was
  written.
* **Access:** already shared with
  `expense-audit-bot@expense-intelligence-508111.iam.gserviceaccount.com` as
  Editor. Verified.
* **Populated:** 45 rows (1981–2025) of live World Bank data, written this
  session.

Columns: `series_id`, `year`, `inflation_rate_pct`, `price_index`, `fetched_at`,
`source`. `price_index` is chained from the annual rates and anchored at 100, so
re-pricing a limit set in year A to year B is **`index(B) / index(A)`** — a lookup
and one division, not a compounding calculation the agent has to get right.
`tests/test_cpi_sheet.py` asserts that division reproduces the engine's own factor
exactly, so Slack and the dashboard cannot disagree about one receipt.

The sync **replaces** the tab rather than appending: the World Bank revises
figures, and appending would leave two rows for the same year with no way to tell
which is current.

Re-run `python scripts/sync_cpi.py` when the World Bank publishes (annually) or
before a demo. **C2 is the n8n-native version of exactly this job** — a cron node
writing the same tab — so when AA builds it, nothing in `api/audit.py` changes.

---

## 6. Credential exposure — resolved

`.env` (FRED key) was committed in `c4542d7`; the service-account JSON in
`fbb9230`. A push attempt was blocked by **GitHub push protection**, which is what
surfaced it.

Resolved: `git filter-branch` stripped both blobs from the three unpushed commits
while preserving all three and their messages (final content byte-identical,
verified by diff against a backup branch). Pushed clean. Backup refs and
`refs/original` deleted, reflog expired, `git gc --prune=now` — all three old
commits confirmed purged from the local object store.

The service-account key was rotated and `.streamlit/secrets.toml` regenerated from
the new key (generated rather than hand-pasted, because the `private_key` field's
embedded newlines are the usual way that file breaks). Verified live against the
sheet.

**Still worth doing:** the FRED key was never rotated. It is now unused by the
project, so this is hygiene rather than exposure.

---

## 7. Bugs found and fixed in existing code

* **Five of six receipts vanished from the dashboard.** `pd.to_datetime` infers a
  format from the first row and coerces everything else to `NaT`. The first
  receipt is ISO; the five SROIE sample receipts are `08/20/10 13:12:01`, so they
  became undated and the date filter silently dropped them. Fixed with
  `format="mixed"`; verified 6 of 6 now parse. Genuinely unparseable rows are now
  surfaced in an expander instead of disappearing.
* **Google Sheets 429 quota errors on any filter interaction.** Streamlit re-runs
  the whole script on every widget change, and each uncached `load_expenses()`
  cost ~8 reads against a 60/minute quota. Fixed with `st.cache_resource` on the
  spreadsheet/worksheet handles and `st.cache_data(ttl=60)` on the loaders;
  `record_decision()` clears the cache so Approve/Reject still updates instantly.
* **`st.date_input` returns a 1-tuple mid-selection**, and the Expense Browser
  indexed `[1]` unconditionally — an `IndexError` waiting for anyone who changed
  the date range. Guarded.
* **A malformed `line_items` cell took down every page** that loads receipts. The
  sheet is hand-editable and n8n has written bad values. Now degrades to `[]`.
* **A test reached the live Google Sheet** and hit a quota error, because
  `api/app.py` binds `receipts_ws` at import time and patching `api.sheets` alone
  missed it. Fixed, plus an autouse fixture that now refuses live access outright.

---

## 8. Corrections to earlier claims

Two things in the previous handoff and the AA punch list were wrong and are now
fixed in place:

1. **`receipt_id = '=ROW()-1'` is not stored as inert text.** Verified against the
   live sheet: Sheets *evaluates* it, so the ids look correct (3, 4, 5, 6) but are
   **positional**. Deleting, inserting or sorting a row silently renumbers
   everything below while the Verdicts and Decisions rows keep pointing at the old
   numbers. Quieter and more damaging than the original claim, and a stronger
   argument for AA.
2. **Category is not broken.** `Audit Engine Input2` does include `submission`
   (unlike its unsuffixed twin), so `submission.category_label` resolves and the
   live data confirms it. Nearly handed AA a non-bug.

---

## 9. Epic E (CFO Dashboard) — assessed, not built

| Ticket | Status |
|---|---|
| E1 shell & navigation | Done |
| E2 spend velocity & leakage | **Partial** — see below |
| E3 policy health trend view | **Not built** — nothing exists |
| E4 review queue + 1-click approve/reject | Built; not demonstrable until C3 lands |
| E5 queryable expense browser | Done |
| E6 QA functional/UX testing | Not started (Mason's) |

**E2's leakage metric measures the wrong thing.** The AC asks for "a running total
of leakage *prevented*". The tile currently sums flagged/high-risk receipts, which
is money *at risk*, not money *saved*. Money actually prevented is the sum of
rejected receipts, which lives in the Decisions tab and is not surfaced anywhere —
so the tile would read £0 saved after Amara rejects ten claims, undercutting the
ROI story she asked for. Should show both.

**E3 is the only dashboard ticket with nothing behind it**, and it is the brief's
own "policy health trends" headline view. The data exists (verdicts carry
`created_at`, receipts carry dates and categories), so it is buildable now with no
external blocker.

---

## 10. Known gaps, stated rather than hidden

* **No currency conversion.** The handbook is GBP; the sample data is USD. A
  non-GBP claim is still compared against the GBP limit and the result carries
  `unconverted_currency: true` plus a sentence telling the reviewer to weigh the
  exchange rate and purchasing power themselves. Amara named both explicitly.
  Closing it needs an FX source keyed on the transaction date (Handbook 12.2).
* **Inflation is annual and ~a year in arrears** (section 4).
* **Attendee count is not in the schema**, so per-head limits divide by 1 unless a
  caller passes `attendee_count` — a shared dinner reads as an overage. One of the
  fields Mason already flagged as missing from B3.
* **The governance prompt has two known fixes outstanding:** it says `$2,000` /
  `$250` where the handbook is GBP, and it does not cover the Miscellaneous
  category at all — which is one of the five headline problems in the brief and
  Amara's specific complaint. Neither is applied yet.
* **C6 and D2 are "function, not endpoint".** The dashboard reads
  `dashboard/data.py` directly and calls `record_decision()` rather than going
  through `/api/expenses` and an approval endpoint. The ACs are met in substance;
  a strict reading of "consuming C6" and "calling D2's approval API" would note
  the missing HTTP hop. Deliberate — there is nowhere to host Flask alongside
  Streamlit Cloud — but present it as a decision rather than let it be found.
* **`discovery_docs/` still uses the three-tier vocabulary.** `tickets.md`'s
  acceptance criteria say "compliant / flagged / high-risk" and
  `data_schema_guide.md` lists the old status values. Those are shared team
  artifacts and the ACs are the PM's, so they were flagged rather than silently
  rewritten.

---

## 11. What's next, in order

1. **Commit this work.** It is all uncommitted. 104 tests pass; `git status` shows
   20 modified files and 2 new ones.
2. **Send AA the C3 hand-off** — `epic_3_tickets.md` now has a why-it-matters table
   and a self-contained, paste-ready prompt for their LLM, updated for the
   two-verdict model. **This is the bottleneck**: C3 and C5 both close on it, and
   the Review Queue stays empty for the demo until it lands.
3. **Paste `SYSTEM_PROMPT` into n8n** — the "AI Contextual Audit" node's
   `jsonBody` → `input[0].content[0].text`, or the Agent node's System Message if
   it has since been converted. **Both copies** (unsuffixed and `2`-suffixed), or
   the two paths judge the same receipt by different rules.
4. **Get Alex to sign off the prompt** (technically A3).
5. **Capture C4 evidence** for MCP-27: `python scripts/c4_demo.py`, paste the
   output into the ticket.
6. **Build E3 and fix E2's leakage metric** — the only dashboard work with no
   external blocker.
7. **Re-test end to end** once AA's fixes land: a real Slack file upload should
   produce rows in both Receipts and Verdicts, with a low-risk receipt landing
   `approved` and never reaching the queue.

---

## 12. Tested vs. not

**Tested:** 104 pytest tests over the audit engine, policy limits, summary
generation, every API endpoint, the CPI sheet writer and the dashboard data layer
— no credentials or network required, and an autouse fixture refuses live sheet
access. Beyond the suite, verified live this session: the World Bank pull and the
resulting inflation figures; the rotated service-account credentials against the
real spreadsheet; the CPI sheet write (45 rows); the dashboard's transforms
against a snapshot of the real sheet data; and both Flask import paths.

**Not tested:** nothing has been seen in a running Streamlit browser session; no
live n8n execution; no OpenAI call from Python; the two-verdict model has never
been exercised by a real receipt travelling the actual Slack pipeline.
