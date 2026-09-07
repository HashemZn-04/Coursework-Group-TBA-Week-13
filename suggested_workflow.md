# Suggested Workflow: Autonomous Expense Intelligence

A five-day build plan — Monday 2026-09-07 through Friday 2026-09-11 — for a team of 4, structured around 4 disciplines: **Project Manager**, **Data Analyst**, **Automation Analyst**, and **Quality Assurance** — one person per role.

This split is by *discipline*, not by pipeline stage, so it's naturally less siloed than splitting by "who owns Slack" vs "who owns the dashboard": almost every feature touches data, automation, and quality, and the PM is threaded through all of it. Each role below has clear **primary ownership** of specific tickets (so nothing falls through the cracks and Jira has a clean assignee per issue), but the expectation is daily cross-contribution — the Data Analyst pairs with the Automation Analyst on the extraction → audit handoff, QA tests each feature as it lands rather than only in Week's-end hardening, and the PM is in every integration conversation, not just standups.

**Mandated tooling:** ticket tracking runs in **Jira** (owned by the PM), automation/orchestration runs on **n8n** (owned by the Automation Analyst), and the dashboard is built in **Streamlit** (owned by the Data Analyst).

---

## Team Structure & Roles

### Project Manager (PM)
**Owns the stakeholder relationship, the backlog, and whether the team is building the right thing.**

- Runs the structured stakeholder interview(s) with Amara to extract explicit and unspoken rules (spend thresholds, "unapproved software" lists, travel policy specifics, what counts as "split-receipting," etc.) and turns them into the **Rules of Play** governance document
- Owns the Jira backlog end-to-end: creating epics/tickets from this plan, keeping priorities (P0/P1/P2) current, running daily standups, and making the call on what gets cut if the week runs short
- Co-owns the content of the **AI Governance Prompt** with the Data Analyst — the PM defines *what* the rules mean in business terms, the Data Analyst is responsible for *how* they're encoded and enforced
- Tracks integration dependencies across roles (e.g. "extraction schema must be locked before Day 2 build starts") and flags risk early rather than at Day 6
- Leads the **Amara-scrutiny review pass**: walking the finished system as if Amara herself were auditing it, checking the output actually matches what she asked for
- Coordinates demo day: script, narrative, and making sure the team is rehearsed

**Best fit for:** someone comfortable running interviews, managing a backlog, and making prioritization calls under time pressure. Not expected to write the Governance Prompt code, but expected to understand it well enough to sign off that it matches the Rules of Play.

### Data Analyst (DA)
**Owns the data model, the audit/decision logic, and the dashboard people actually look at.**

- Designs the shared receipt data schema (the contract every other role builds against) and the database schema for receipts, verdicts, approvals, and the audit trail
- Implements the **Policy Match** and **Contextual Validation** logic — the code that takes an extracted receipt, runs it against the PM's Governance Prompt, and layers in CPI/benchmark data to judge "Good Deal" vs "Policy Violation"
- Builds the **"CFO Eyes" Dashboard** in Streamlit: spend velocity, leakage, policy health trends, the queryable expense browser, and the 1-click approve/reject queue
- Owns the analytical stretch goals end-to-end: **Predictive Spending** (regression forecast) and **Fraud Clustering** (unsupervised clustering for "Syndicated Spending"), both via scikit-learn
- Owns the **Agentic Interface** stretch goal (natural-language Q&A over the dashboard data)
- Works closely with the Automation Analyst on the handoff points: what shape of data n8n hands to the audit engine, and what shape of verdict the audit engine hands back for n8n to route to Slack

**Best fit for:** someone comfortable with data modeling, basic stats/ML (scikit-learn level), API design, and building UI in Python (Streamlit keeps this role entirely in one language).

### Automation Analyst (AA)
**Owns everything built as an n8n workflow — the plumbing that makes the system "zero-touch."**

- Builds the **Zero-Touch Ingestion** trigger as an n8n workflow: native **Slack Trigger node** (and optionally an **Email Trigger/IMAP node**) catching incoming JPG/PNG/PDF submissions
- Builds the **Vision Extraction** step: an **HTTP Request node** calling a vision-capable LLM API, mapping the response into the Data Analyst's shared schema
- Chains extraction into the audit engine (an HTTP Request node calling the Data Analyst's audit API) so a receipt flows Slack → extraction → audit with no manual steps
- Builds the **instant compliance feedback** loop: once a verdict comes back, a Slack node replies to the submitter with the outcome and reasoning
- Builds the **scheduled CPI/market-intelligence pull** (Cron Trigger → HTTP Request → write to DB) that feeds the Data Analyst's Contextual Validation logic
- Builds the **human-in-the-loop notification workflow**: a Webhook node triggered by a dashboard approve/reject action, posting the outcome back to the submitter in Slack
- Owns the **Voice-to-Memo** stretch goal end-to-end: Slack Trigger (voice note) → HTTP Request to a speech-to-text API → HTTP Request to the LLM for memo generation → write to DB
- Handles malformed/illegible input gracefully using n8n's error-handling/branching nodes — this is where demo-day failures usually happen, so budget real time for it

**Best fit for:** someone comfortable with low-code workflow tools and API integration. This role is closer to "workflow engineer" than "backend engineer" — n8n does most of the plumbing, so deep coding background isn't required.

### Quality Assurance (QA)
**Owns whether what got built actually works, end to end — not just at the end of the week, but continuously.**

- Writes a labeled test set (compliant / borderline / violation examples) against the Rules of Play and uses it to validate the Governance Prompt's false-positive/false-negative rate as the PM and Data Analyst iterate it
- Validates extraction accuracy: runs the Automation Analyst's OCR/vision pipeline against a ground-truth sample set and reports where it drifts
- Spot-checks audit verdicts against the Rules of Play to confirm the Data Analyst's Policy Match logic is actually enforcing what the PM documented
- Verifies the audit trail is intact end to end: for any receipt, can you reconstruct what was submitted, what was decided, why, and what the human did about it
- Functionally tests the Streamlit dashboard (filters, approve/reject reflecting correctly in the DB, charts matching underlying data) and the Slack feedback loop (message accuracy and timing)
- Runs the full end-to-end pipeline test across the complete sample dataset and constructs deliberate edge cases: duplicate submissions, split-receipting attempts, corrupted/non-receipt files
- Owns the demo dry-run: rehearsing the live path with the PM and flagging anything not stable enough to show live
- Maintains the bug/defect list in Jira (paired with the PM's backlog) so nothing found mid-week gets lost

**Best fit for:** someone methodical who's comfortable defining acceptance criteria, constructing adversarial test cases, and pushing back when something "mostly works."

---

## Responsibility Matrix

Primary owner listed first; contributors follow. Every epic has PM and QA touchpoints even where they aren't the primary builder — that's intentional.

| Workstream | Primary | Contributors |
|---|---|---|
| Stakeholder interview & Rules of Play | **PM** | DA (technical rule capture) |
| AI Governance Prompt | **DA** | PM (rule content/sign-off), QA (test set) |
| Slack/email ingestion (n8n) | **AA** | DA (schema) |
| Vision extraction (OCR) | **AA** | QA (accuracy validation) |
| Database & receipt schema | **DA** | AA, QA (sign-off) |
| CPI / contextual validation | **DA** | AA (scheduled pull workflow) |
| Policy Match / audit engine | **DA** | PM, QA (verdict spot-checks) |
| Human-in-the-loop approve/reject | **DA** (API) / **AA** (Slack notify) | PM (state design), QA (audit trail integrity) |
| Streamlit dashboard | **DA** | AA (webhook wiring), QA (functional testing) |
| Slack compliance feedback | **AA** | QA (message accuracy) |
| Voice-to-Memo (stretch) | **AA** | PM (memo content rules), QA (transcription/memo validation) |
| Predictive Spending (stretch) | **DA** | QA (sanity-check outputs) |
| Fraud Clustering (stretch) | **DA** | QA (false-positive check) |
| Agentic Interface (stretch) | **DA** | AA (if exposed as a callable tool), QA (question-bank testing) |
| Jira backlog & prioritization | **PM** | QA (defect log) |
| End-to-end testing & edge cases | **QA** | whole team |
| Amara-scrutiny review | **PM** | QA |
| Demo prep | **PM** (script) | QA (rehearsal), whole team |

---

## Why Streamlit for the dashboard

Given the brief's dashboard requirements — real-time charts, a 1-click approve/reject workflow, surfacing ML model outputs (forecasts, clusters), and an agentic natural-language interface — the three free options were weighed as follows:

- **Tableau Public** — ruled out. Published Tableau Public dashboards are public by design; there is no free private-hosting tier, which is a hard conflict with confidential CFO financial data. It also has no native way to build an interactive 1-click approve/reject action.
- **Airtable** — viable but limited. Its free-tier Interface Designer can do basic buttons/forms with less code, but it's weak for custom charts, cannot natively host ML model outputs (regression forecasts, cluster visualizations) well, and free-tier record limits are tight for a growing expense dataset.
- **Streamlit (chosen)** — free (Streamlit Community Cloud hosting), fully custom, and Python-native. It handles interactive buttons, custom charts, and — critically — directly displays scikit-learn model output and supports the agentic Q&A stretch goal as a straightforward LLM call, without needing a second framework. It also keeps the Data Analyst's whole scope (data model → analysis → dashboard) in one language.

---

## Suggested Tooling

No software beyond the mandated ticket tracking (Jira), automation (n8n), and dashboard (Streamlit) is fixed by the brief — default to free tooling everywhere else.

| Need | Suggested option | Primary owner |
|---|---|---|
| Ticket tracking / PM | **Jira** (free tier, up to 10 users — covers a 4-person team) | PM |
| Automation / orchestration | **n8n** (free, self-hosted or n8n Cloud free tier) | AA |
| Slack integration | n8n's native **Slack Trigger** and **Slack** nodes — no separate Slack app/Bolt SDK build needed | AA |
| Email intake | n8n's native **Email Trigger (IMAP)** node | AA |
| Dashboard | **Streamlit**, hosted free on Streamlit Community Cloud | DA |
| Database | PostgreSQL (free) for the real build; SQLite is fine for a one-week prototype if setup time matters more than realism | DA |
| LLM (extraction, governance, summarization) | Whatever LLM API the team already has trial/free credits for (e.g. Claude, via this environment) — one provider for everything keeps prompt behavior consistent, called from n8n's HTTP Request node | DA (prompt design) / AA (calling it) |
| OCR / vision fallback | Vision-capable LLM call for extraction (via n8n); Tesseract OCR as a free, fully local fallback if API quota is a concern | AA |
| Speech-to-text (voice memo) | OpenAI Whisper (open-source, self-hostable) or a free hosted Whisper API endpoint, called from n8n | AA |
| Market intelligence / CPI data | BLS (Bureau of Labor Statistics) public CPI API or FRED API — both free, no key cost, pulled on a schedule via an n8n Cron Trigger workflow | AA (pull) / DA (consumption logic) |
| Regression / clustering (stretch) | scikit-learn (free, open-source) | DA |
| Defect / bug tracking | Jira (same board, separate issue type — no need for a second free tool like TestRail) | QA |
| Hosting for demo | Local demo is fine for a 1-week academic project; if hosting, Streamlit Community Cloud (dashboard, free) + a lightweight free host for any backend API (Railway/Render free tier) + n8n Cloud free tier or a local n8n instance | DA / AA |

---

## Five-Day Timeline (Mon–Fri)

Compressed from the brief's one-week allowance into 5 working days. Full task-by-task sequencing (with priorities) lives in the ordering table at the top of `tickets.md` — this section is the narrative view of the same plan. Today's (Monday's) detailed breakdown also has its own standalone file: `discovery_guide.md`.

**Day 1 — Monday 2026-09-07 — Discovery & Setup**
- PM runs the stakeholder interview with Amara; starts the Rules of Play doc; sets up the full Jira backlog (see `tickets.md`) with assignees; sketches the approve/reject state machine
- AA stands up the n8n instance and builds the first skeleton workflow (Slack Trigger → log payload)
- DA proposes the receipt data schema, designs the database schema, and stands up the Streamlit app shell against mock data
- QA drafts the labeled governance test-set structure and reviews the shared receipt schema for testability
- Whole team agrees on the receipt data schema before the day ends — this is the contract every role builds against
- See `discovery_guide.md` for the detailed per-role checklist for today

**Day 2 — Tuesday 2026-09-08 — Core Pipelines, Independent Build**
- PM: Governance Prompt v1 drafted jointly with DA from Monday's interview notes
- AA: Slack intake workflow extended through vision extraction; malformed-input handling; CPI scheduled-pull workflow built; submission-acknowledgment message added
- DA: audit engine skeleton wired to Governance Prompt v1
- QA: validates extraction accuracy as soon as AA has a working pipeline

**Day 3 — Wednesday 2026-09-09 — Integration & Human-in-the-Loop**
- AA's n8n extraction workflow calls DA's audit engine live; instant compliance feedback goes out in Slack; approve/reject decision-notification workflow built
- DA: Policy Match and Contextual Validation live; high-risk routing and the approved-expense query API built; approve/reject API built; dashboard views (spend velocity, leakage, policy health, review queue, expense browser) wired to real data
- QA spot-checks live verdicts against the Rules of Play, verifies audit-trail integrity across the approve/reject cycle, and checks Slack feedback accuracy — reporting findings to PM + DA continuously
- PM facilitates the fix loop between QA's findings and DA's prompt/logic tuning; keeps iterating the Governance Prompt against real sample data

**Day 4 — Thursday 2026-09-10 — Stretch Goals & Dashboard Hardening**
- AA builds the Voice-to-Memo workflow end-to-end
- DA builds Predictive Spending, Fraud Clustering, and the Agentic Interface (in that priority order — cut from the bottom if behind)
- QA functionally tests the dashboard and validates each stretch goal as it lands (transcription accuracy, forecast sanity-check, cluster false-positive check, Q&A question bank)
- PM makes scope-cut calls based on QA's findings and remaining time

**Day 5 — Friday 2026-09-11 — Final Testing & Demo**
- QA runs the full end-to-end pipeline test across the entire sample dataset and the deliberate edge-case pass (duplicates, split-receipting, bad input)
- PM leads the Amara-scrutiny review pass: does the paper trail actually hold up to audit, would a real senior auditor agree with the calls made?
- PM finalizes the Governance & Documentation deliverable and the scope-cut log; QA runs the final demo dry-run and PM prepares a backup recorded run in case live Slack/n8n/API calls flake
- Present: problem → pipeline walkthrough → live demo → stretch goals → what we'd build next

---

## Collaboration Notes

- **The receipt schema is the team's shared contract.** Lock it on Day 1 and change it deliberately, not silently — every n8n workflow, the audit engine, and the Streamlit dashboard all depend on it.
- **QA tests continuously, not just in Epic K.** Waiting until Day 6 to find out the extraction pipeline drifts on blurry receipts is too late to fix well — QA should be validating each piece within a day of it going live.
- **PM and DA should sync daily on the Governance Prompt**, even briefly — it's a shared artifact (PM owns the business rules, DA owns the technical enforcement) and drifts apart fast if decoupled.
- **Build against real sample data from Day 2 onward**, not synthetic happy-path data — the brief's whole premise is that messy real-world receipts break naive systems.
- **Keep n8n workflows small and named clearly** (one workflow per trigger/purpose) rather than one giant workflow — it's much easier to debug and demo individual pieces that way.
- **Everything lives in Jira**, including stretch goals as their own epics and QA's defect log, so scope cuts on Day 5-6 are a matter of moving tickets out of the sprint rather than a scramble.
- **Cut stretch goals in this order if the week runs short:** Agentic Interface → Fraud Clustering → Predictive Spending → Voice-to-Memo. The core pipeline (ingestion → audit → dashboard → Slack feedback) is the deliverable; stretch goals are genuinely optional.
