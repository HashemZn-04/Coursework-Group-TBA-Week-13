# Tickets: Autonomous Expense Intelligence

Owner roles: **PM** = Project Manager, **DA** = Data Analyst, **AA** = Automation Analyst, **QA** = Quality Assurance. Roles are split by discipline, not pipeline stage — the "primary" owner is who's accountable for the ticket in Jira, but cross-role contribution is expected (see `suggested_workflow.md`'s Responsibility Matrix).

Priority: **P0** = core deliverable, project fails without it. **P1** = expected deliverable per brief. **P2** = stretch goal, cut first if time runs short.

**Ticket tracking:** import these into **Jira** as the project's backlog, one epic per `##` heading below, each numbered item as a story/task under it. Ticket IDs (A1, B1, etc.) map directly to Jira issue keys for traceability between this doc and the board. QA verification tickets (the last item in each epic) should be created as sub-tasks or linked "blocks release" issues against the feature tickets they check.

---

## Epic A — Requirement Discovery & Governance

**A1. Conduct structured stakeholder interview with Amara** — *P0, PM*
Run a live interview to extract explicit and unspoken business rules: spend thresholds, unapproved-vendor/software list, travel policy specifics, what counts as "split-receipting," what she currently checks manually. Capture verbatim quotes where possible — they surface unstated rules better than paraphrasing.
*Acceptance criteria:* Written interview notes covering at least: spend thresholds by category, unapproved spend categories, travel policy rules, current audit red flags Amara personally checks for.

**A2. Draft the "Rules of Play" governance document** — *P0, PM*
Translate A1's raw notes into a structured rules document (per category: rule, threshold, rationale, source quote from Amara) that maps 1:1 onto what the AI Governance Prompt will enforce.
*Acceptance criteria:* Document reviewable by Amara; every rule in it traces to an interview note; every rule has a corresponding enforcement point in the Governance Prompt (A3).

**A3. Build v1 of the AI Governance Prompt** — *P0, DA (content co-owned with PM)*
Codify the Rules of Play into a prompt/config that the audit engine (Epic C) calls per receipt to produce a policy verdict + reasoning. DA is responsible for how the rules are encoded and enforced; PM signs off that the encoded logic actually matches what Amara asked for. Agree the input/output JSON contract with AA before building it out, since AA's n8n workflow will call it.
*Acceptance criteria:* Prompt takes a structured receipt object as input and returns a structured verdict (compliant / flagged / high-risk) with a natural-language reason. Tested against at least 5 sample receipts spanning compliant, borderline, and violating cases. PM has signed off the mapping against the Rules of Play.

**A4. Iterate Governance Prompt against real sample data** — *P1, DA + PM, tested by QA*
Run the prompt against the facilitator-provided sample expense dataset once available; tune for false positives/negatives using QA's labeled test set (A6).
*Acceptance criteria:* False-positive and false-negative cases logged with example receipts; prompt revised at least once based on QA's findings; revision rationale documented.

**A5. Finalize Governance & Documentation deliverable** — *P0, PM*
Polish A2 into the presentation-ready deliverable described in the brief's "Planned Outputs."
*Acceptance criteria:* Document is self-contained, readable by a non-technical stakeholder, and explicitly shows the mapping from business rule → technical enforcement.

**A6. QA: Build labeled governance test set** — *P0, QA*
Construct a set of sample receipts labeled by hand (compliant / borderline / violation) directly against the Rules of Play, independent of what the Governance Prompt currently outputs — this is the ground truth A4 tunes against.
*Acceptance criteria:* At least 15 labeled examples covering every major rule category in the Rules of Play, with the expected verdict and reasoning documented for each; test set is versioned so re-runs are comparable across prompt iterations.

---

## Epic B — Zero-Touch Ingestion (n8n)

**B1. Build n8n workflow: Slack receipt-submission trigger** — *P0, AA*
Stand up an n8n instance and build a workflow using the native **Slack Trigger node** watching a dedicated channel/DM for JPG/PNG/PDF file uploads. No custom Slack app/Bolt code required.
*Acceptance criteria:* Uploading a file in the configured Slack channel fires the n8n workflow with the file payload available to downstream nodes.

**B2. (Optional) n8n workflow: email intake trigger** — *P2, AA*
Add an **Email Trigger (IMAP)** node to a free mailbox as an alternate submission path, feeding the same downstream workflow as B1.
*Acceptance criteria:* An email with an attached receipt image/PDF triggers the n8n workflow and enters the same processing path as B1. Cut this ticket first if Slack-only intake is sufficient for the demo.

**B3. Define shared receipt data schema** — *P0, DA (whole-team sign-off)*
Agree on the structured object every downstream component (n8n workflows, audit engine, Streamlit dashboard) consumes: merchant, date, line items, tax, total, currency, submitter, source channel, raw file reference.
*Acceptance criteria:* Schema documented and agreed by all four roles before Day 2 build starts; changes after that point are communicated to the whole team via PM.

**B4. Build n8n workflow step: vision extraction (OCR)** — *P0, AA*
Chain an **HTTP Request node** off B1's trigger, calling a vision-capable LLM API to extract merchant, date, line items, tax, and total from the raw file, mapped into the B3 schema via n8n's data transform nodes. Use Tesseract OCR as a free local fallback if API quota is a concern.
*Acceptance criteria:* Given 10 varied sample receipts (different formats/quality) run through the workflow, extraction correctly captures merchant + date + total for at least 8; failures are logged (via an n8n error-handling branch), not silently dropped.

**B5. Handle malformed/illegible receipt input gracefully** — *P1, AA*
Use n8n's IF/error-handling nodes to branch on unreadable images, corrupted PDFs, or receipts missing required fields into a "needs manual review" path instead of letting the workflow fail.
*Acceptance criteria:* A deliberately bad input (blurry image, non-receipt image, empty PDF) produces a clear "needs manual review" state in the workflow instead of a crash or silent bad data.

**B6. Chain extraction workflow into the audit pipeline** — *P0, AA + DA*
Extend B4's n8n workflow with an HTTP Request node calling DA's audit engine API with the extracted data.
*Acceptance criteria:* A Slack-submitted receipt flows end-to-end from upload through the n8n workflow to a stored, policy-evaluated verdict with no manual intervention.

**B7. QA: Validate extraction accuracy against ground truth** — *P0, QA*
Run AA's extraction pipeline against a hand-verified ground-truth sample set (separate images with manually recorded correct merchant/date/total) and report drift.
*Acceptance criteria:* Accuracy report showing extraction correctness rate against ground truth, broken down by receipt quality/format; any systematic failure pattern (e.g. a specific receipt layout) is filed as a Jira bug against B4.

---

## Epic C — The Intelligent Audit Engine

**C1. Design database schema for receipts, verdicts, and audit trail** — *P0, DA*
Model receipts, extracted line items, policy verdicts, approval/rejection decisions, and timestamps such that every decision is traceable (the brief's "paper trail auditors can follow"). Both n8n workflows and the Streamlit dashboard read/write against this schema.
*Acceptance criteria:* Schema supports reconstructing, for any receipt, what was submitted, what the AI decided, why, and what the human did about it.

**C2. Build n8n workflow: scheduled CPI / market intelligence pull** — *P0, AA (consumption logic by DA)*
Build an n8n workflow with a **Cron Trigger node** calling a free public CPI/benchmark API (e.g. BLS or FRED) on a schedule (e.g. daily), writing results into the database via a Postgres node (or an HTTP call to DA's API).
*Acceptance criteria:* Given a spend category and amount, the system can return whether it's within, above, or below the current benchmark range, refreshed at the defined interval — verifiable by checking the DB updates after a scheduled run.

**C3. Implement Policy Match against Governance Prompt** — *P0, DA (rule content from PM)*
Build the audit API that B6's n8n workflow calls with each incoming receipt, invoking A3's Governance Prompt and persisting the verdict per C1's schema.
*Acceptance criteria:* Every ingested receipt receives a stored policy verdict (compliant / flagged / high-risk) with reasoning text, within a reasonable latency for a live demo (a few seconds).

**C4. Implement Contextual Validation (inflation-aware)** — *P0, DA*
Combine C2's benchmark data with the receipt amount to flag "Good Deal" vs "Policy Violation" relative to current economic conditions, not a static limit.
*Acceptance criteria:* A receipt priced above a static old limit but within current inflation-adjusted benchmark is correctly classified as acceptable (and vice versa) — demonstrated with at least one constructed example.

**C5. Build High-Risk routing & natural-language summary generation** — *P0, DA (content) + AA (Slack delivery)*
When C3/C4 produce a high-risk verdict, DA's API generates a natural-language summary as part of its response, so AA's n8n workflow can post it to Slack via a Slack node and make it available to the dashboard queue.
*Acceptance criteria:* A high-risk receipt produces a human-readable summary (what was flagged, why, amount, submitter), delivered to Slack via n8n and available to the Streamlit dashboard via an API.

**C6. Expose approved-expense query API for dashboard** — *P0, DA*
Build the API/query layer the Streamlit dashboard uses for "all approved expenses queryable" (filters: date range, category, employee, amount).
*Acceptance criteria:* Dashboard can retrieve filtered/paginated approved expense data without needing direct DB access.

**C7. QA: Spot-check audit verdicts against Rules of Play** — *P0, QA*
Sample live verdicts produced by C3/C4 as they come in and manually check them against the PM's Rules of Play document — not the prompt's own stated reasoning, but the actual business rule.
*Acceptance criteria:* At least 20 live verdicts reviewed across the build week; disagreements between the system's verdict and the documented rule are logged as Jira bugs against A3/C3 with the specific receipt and expected vs. actual outcome.

---

## Epic D — Human-in-the-Loop Workflow

**D1. Design approval/rejection state machine** — *P0, PM (implementation by DA)*
Define the lifecycle of a flagged receipt: pending → approved/rejected → (optionally) escalated, and what triggers each transition.
*Acceptance criteria:* State diagram or equivalent doc; every state has a defined trigger and resulting action (e.g. reject → n8n notifies submitter in Slack).

**D2. Build 1-click approve/reject API** — *P0, DA*
Backend endpoint(s) the Streamlit dashboard calls to record Amara's decision on a flagged receipt, updating C1's audit trail.
*Acceptance criteria:* Approving or rejecting a flagged receipt from the dashboard updates its stored state and is reflected in the audit trail with timestamp and decision-maker.

**D3. Build n8n workflow: notify submitter of decision outcome** — *P1, AA*
Build an n8n workflow triggered by a **Webhook node** (called from D2 when a decision is made), posting a Slack message to the original submitter via a Slack node explaining the outcome.
*Acceptance criteria:* Rejecting a receipt in the Streamlit dashboard triggers the n8n webhook and results in a Slack message to the original submitter explaining the outcome.

**D4. QA: Verify audit trail integrity across the approve/reject cycle** — *P0, QA*
For a sample of flagged receipts, walk the full cycle (flagged → reviewed → decided → submitter notified) and confirm every step is correctly and immutably recorded.
*Acceptance criteria:* For at least 5 test receipts pushed through the full human-in-the-loop cycle, the audit trail correctly shows who decided what and when, with no missing or overwritten records; gaps filed as Jira bugs against C1/D2.

---

## Epic E — CFO Dashboard (Streamlit)

**E1. Build dashboard shell & navigation** — *P0, DA*
Stand up the Streamlit app skeleton (spend overview, review queue, expense browser as separate pages/tabs).
*Acceptance criteria:* Navigable Streamlit app runnable locally (and deployable free on Streamlit Community Cloud), pointed at mock data initially.

**E2. Build spend velocity & leakage visualizations** — *P1, DA*
Real-time (or near-real-time) charts showing spend velocity and identified "leakage" (money saved via flags/rejections) per the brief's dashboard requirement, using Streamlit's native charting.
*Acceptance criteria:* Dashboard shows at least: total spend over time, spend by category, and a running total of leakage prevented, sourced from real backend data (C6).

**E3. Build policy health trend view** — *P1, DA*
Visualization of policy compliance trends over time (e.g. % flagged over time, most-violated rules).
*Acceptance criteria:* At least one chart showing compliance rate or violation breakdown trending over the sample data's time range.

**E4. Build High-Risk review queue with 1-click approve/reject** — *P0, DA (webhook wiring with AA)*
The Streamlit view consuming C5's summaries and calling D2's approval API via button widgets.
*Acceptance criteria:* Amara-persona user can view a flagged receipt's summary and approve/reject it in one click from the dashboard; queue updates without a full manual refresh.

**E5. Build queryable expense browser** — *P0, DA*
Searchable/filterable table of all approved expenses (the brief's "Data Analysis" output), consuming C6, using Streamlit's dataframe and filter widgets.
*Acceptance criteria:* User can filter by date range, category, employee, and amount, and results update accordingly.

**E6. QA: Functional and UX testing of the dashboard** — *P0, QA*
Test every dashboard interaction: filters return correct results, approve/reject buttons correctly update the DB and reflect in the audit trail, charts match their underlying data.
*Acceptance criteria:* Written test log covering each view in E1-E5; any mismatch between displayed data and the underlying database is filed as a Jira bug with reproduction steps.

---

## Epic F — Employee Compliance Feedback (n8n + Slack)

**F1. Extend intake workflow with submission acknowledgment** — *P0, AA*
Add a Slack node to B1's workflow so the employee gets an immediate acknowledgment upon upload, before the audit result is ready.
*Acceptance criteria:* Employee uploads a receipt in Slack and receives an acknowledgment message within a few seconds.

**F2. Extend intake workflow with instant compliance feedback** — *P0, AA*
Once C3/C4 return a verdict (via B6/C5), add a Slack node posting the outcome (compliant / needs review / rejected) and reasoning back to the submitter in-thread.
*Acceptance criteria:* Submitting a policy-violating receipt produces a Slack reply within the demo's expected latency, stating what was flagged and why, entirely via the n8n workflow.

**F3. QA: Verify Slack feedback accuracy and timing** — *P0, QA*
Submit a range of test receipts (compliant, flagged, illegible) via Slack and confirm the feedback message content matches the actual stored verdict, and arrives within an acceptable time for a live demo.
*Acceptance criteria:* For at least 10 test submissions, Slack feedback text matches the stored verdict/reasoning exactly, and response latency is logged; anything over ~10 seconds is flagged to AA as a performance issue.

---

## Epic G — Stretch Goal: Voice-to-Memo (n8n)

**G1. Build n8n workflow: voice note intake** — *P2, AA*
Extend the Slack Trigger workflow (or add a new one) to catch voice note uploads for a missing receipt.
*Acceptance criteria:* A voice note file submitted via Slack triggers the n8n workflow and is passed to G2.

**G2. Add n8n workflow step: transcribe voice note** — *P2, AA*
Add an HTTP Request node calling a speech-to-text API (e.g. Whisper) to transcribe the voice note.
*Acceptance criteria:* A sample voice note produces a reasonably accurate text transcript, logged for review.

**G3. Add n8n workflow step: generate compliant memo from transcript** — *P2, AA (memo content rules from PM)*
Add an HTTP Request node calling an LLM prompt — co-designed with PM so it respects governance rules for what a valid "missing receipt" justification requires — to produce a structured, policy-compliant memo, written to the database via a final node.
*Acceptance criteria:* Given a transcript describing a plausible missing-receipt scenario, the workflow outputs a memo containing the required fields (amount, date, merchant if known, justification) suitable for the audit trail (C1).

**G4. QA: Validate transcription accuracy and memo compliance** — *P2, QA*
Test G2's transcription against a set of recorded voice notes with known correct text, and check G3's generated memos against PM's requirements for a valid missing-receipt justification.
*Acceptance criteria:* Transcription accuracy documented against at least 5 test voice notes; generated memos checked against PM's required-field list, with gaps filed as Jira bugs against G3.

---

## Epic H — Stretch Goal: Predictive Spending

**H1. Build regression model for next-month travel spend forecast** — *P2, DA*
Using scikit-learn, build a simple regression model forecasting next month's travel spend based on historical spend data and current 2026 price volatility (C2's benchmark data).
*Acceptance criteria:* Model trained on available sample/historical travel spend data produces a next-month forecast with a documented method (even if simple linear/polynomial regression) and a sanity-checked output range.

**H2. Surface spending forecast on dashboard** — *P2, DA*
Expose H1's forecast via API and display it on the Streamlit dashboard (e.g. a forecast line alongside actual spend in E2).
*Acceptance criteria:* Dashboard shows a forecasted next-month travel spend figure alongside historical actuals, sourced from H1's model output.

**H3. QA: Sanity-check forecast against historical trend** — *P2, QA*
Compare H1's forecast output against a naive baseline (e.g. simple trailing average) and flag if the model's output is wildly implausible.
*Acceptance criteria:* Forecast output compared against at least one naive baseline; any forecast more than a documented threshold away from the baseline is flagged to DA for review before demo day.

---

## Epic I — Stretch Goal: Fraud Clustering

**I1. Build "Syndicated Spending" clustering model** — *P2, DA*
Using scikit-learn (e.g. KMeans/DBSCAN), identify groups of employees consistently submitting similar non-flagged expenses — a pattern individual-receipt policy checks would miss.
*Acceptance criteria:* Model runs against the sample expense dataset and produces at least one identifiable cluster with a documented similarity basis (e.g. same vendor + similar amount + overlapping timeframe across multiple employees).

**I2. Surface fraud clusters on dashboard** — *P2, DA*
Expose I1's output as a reviewable list/view on the Streamlit dashboard (separate from the individual-receipt review queue in E4).
*Acceptance criteria:* Dashboard shows detected clusters with the employees/receipts involved and the basis for flagging, and lets Amara mark a cluster as reviewed.

**I3. QA: Validate clustering doesn't false-positive on legitimate shared expenses** — *P2, QA*
Construct test cases of legitimate shared spend patterns (e.g. a team consistently expensing the same approved vendor for a valid reason) and confirm I1 doesn't flag them as fraud clusters.
*Acceptance criteria:* At least 3 constructed legitimate-shared-spend scenarios run through I1; any false-positive flag is documented and reported to DA to adjust the clustering criteria.

---

## Epic J — Stretch Goal: Agentic Interface

**J1. Build natural-language Q&A over dashboard data** — *P2, DA*
Allow Amara to ask free-text questions (e.g. "how much did we spend on software last quarter?") in the Streamlit dashboard and get an answer derived from real backend data (C6) via a direct LLM call, not a hallucinated response.
*Acceptance criteria:* At least 3 distinct natural-language questions produce correct answers grounded in the actual stored expense data, with the system declining or caveating when it lacks the data to answer confidently.

**J2. QA: Test Q&A against a question bank** — *P2, QA*
Build a bank of at least 10 natural-language questions with known correct answers (derived manually from the data) and run them against J1.
*Acceptance criteria:* Question bank documented with expected answers; any incorrect or hallucinated answer is filed as a Jira bug against J1 with the question and the actual vs. expected answer.

---

## Epic K — Testing, Hardening & Demo Prep

**K1. End-to-end pipeline test across full sample dataset** — *P0, QA*
Run every sample receipt through the complete pipeline (Slack submission → n8n extraction workflow → audit → Streamlit dashboard/Slack outcome) and log failures.
*Acceptance criteria:* 100% of sample receipts produce a terminal state (compliant, flagged-and-resolved, or explicitly needs-manual-review) with no unhandled errors, verifiable in n8n's execution log.

**K2. Edge case pass: duplicates, split-receipting, bad input** — *P1, QA*
Deliberately construct and test: a duplicate submission across months, a split-receipting attempt, and a corrupted/non-receipt file.
*Acceptance criteria:* Each constructed edge case is either correctly caught by the audit engine or fails gracefully (no crash, no silent miscategorization); results logged in Jira.

**K3. Amara-scrutiny review pass** — *P1, PM (supported by QA)*
Walk through the full system as if Amara herself were auditing it: does the paper trail hold up, do the flagged reasons make sense, would a real senior auditor agree with the calls made?
*Acceptance criteria:* Written review notes; any credibility gaps found are either fixed or explicitly called out as known limitations for the presentation.

**K4. Demo script & backup recording** — *P0, PM (rehearsal run by QA)*
Prepare and rehearse the live demo path; record a backup run in case live Slack/n8n/API calls fail during presentation.
*Acceptance criteria:* Demo script covering problem → pipeline walkthrough → live demo → stretch goals rehearsed at least once end-to-end by QA; backup recording exists.

**K5. Sprint retro & scope-cut log** — *P1, PM*
Document what was cut from the original scope (e.g. email intake, specific stretch goals) and why, so the presentation can speak to it directly rather than it looking like an oversight.
*Acceptance criteria:* Short written log of cut/descoped items with rationale, ready to reference if asked about during the presentation.

## Execution Order

The full backlog, grouped by epic and sequenced in the order it should be worked, mapped onto the 5-day schedule (Mon 2026-09-07 – Fri 2026-09-11) from `suggested_workflow.md`. Use the `#` column as the master sequence within a day; priorities (already assigned per ticket above) are repeated here so sequencing and priority can be read together without digging into ticket bodies.

| # | Day | Epic | Ticket | Title | Priority | Owner |
|---|---|---|---|---|---|---|
| 1 | Mon 9/7 | A | A1 | Conduct structured stakeholder interview with Amara | P0 | PM |
| 2 | Mon 9/7 | B | B3 | Define shared receipt data schema | P0 | DA |
| 3 | Mon 9/7 | C | C1 | Design database schema for receipts, verdicts, and audit trail | P0 | DA |
| 4 | Mon 9/7 | B | B1 | Build n8n workflow: Slack receipt-submission trigger | P0 | AA |
| 5 | Mon 9/7 | D | D1 | Design approval/rejection state machine | P0 | PM |
| 6 | Mon 9/7 | A | A6 | QA: Build labeled governance test set | P0 | QA |
| 7 | Mon 9/7 | E | E1 | Build dashboard shell & navigation | P0 | DA |
| 8 | Mon 9/7 | A | A2 | Draft the "Rules of Play" governance document | P0 | PM |
| 9 | Tue 9/8 | A | A3 | Build v1 of the AI Governance Prompt | P0 | DA + PM |
| 10 | Tue 9/8 | B | B4 | Build n8n workflow step: vision extraction (OCR) | P0 | AA |
| 11 | Tue 9/8 | F | F1 | Extend intake workflow with submission acknowledgment | P0 | AA |
| 12 | Tue 9/8 | C | C2 | Build n8n workflow: scheduled CPI / market intelligence pull | P0 | AA |
| 13 | Tue 9/8 | B | B5 | Handle malformed/illegible receipt input gracefully | P1 | AA |
| 14 | Tue 9/8 | B | B2 | (Optional) n8n workflow: email intake trigger | P2 | AA |
| 15 | Tue 9/8 | B | B7 | QA: Validate extraction accuracy against ground truth | P0 | QA |
| 16 | Wed 9/9 | B | B6 | Chain extraction workflow into the audit pipeline | P0 | AA + DA |
| 17 | Wed 9/9 | C | C3 | Implement Policy Match against Governance Prompt | P0 | DA |
| 18 | Wed 9/9 | C | C4 | Implement Contextual Validation (inflation-aware) | P0 | DA |
| 19 | Wed 9/9 | C | C5 | Build High-Risk routing & natural-language summary generation | P0 | DA + AA |
| 20 | Wed 9/9 | C | C6 | Expose approved-expense query API for dashboard | P0 | DA |
| 21 | Wed 9/9 | D | D2 | Build 1-click approve/reject API | P0 | DA |
| 22 | Wed 9/9 | D | D3 | Build n8n workflow: notify submitter of decision outcome | P1 | AA |
| 23 | Wed 9/9 | F | F2 | Extend intake workflow with instant compliance feedback | P0 | AA |
| 24 | Wed 9/9 | E | E2 | Build spend velocity & leakage visualizations | P1 | DA |
| 25 | Wed 9/9 | E | E3 | Build policy health trend view | P1 | DA |
| 26 | Wed 9/9 | E | E4 | Build High-Risk review queue with 1-click approve/reject | P0 | DA + AA |
| 27 | Wed 9/9 | E | E5 | Build queryable expense browser | P0 | DA |
| 28 | Wed 9/9 | A | A4 | Iterate Governance Prompt against real sample data | P1 | DA + PM, QA |
| 29 | Wed 9/9 | C | C7 | QA: Spot-check audit verdicts against Rules of Play | P0 | QA |
| 30 | Wed 9/9 | D | D4 | QA: Verify audit trail integrity across the approve/reject cycle | P0 | QA |
| 31 | Wed 9/9 | F | F3 | QA: Verify Slack feedback accuracy and timing | P0 | QA |
| 32 | Thu 9/10 | G | G1 | Build n8n workflow: voice note intake | P2 | AA |
| 33 | Thu 9/10 | G | G2 | Add n8n workflow step: transcribe voice note | P2 | AA |
| 34 | Thu 9/10 | G | G3 | Add n8n workflow step: generate compliant memo from transcript | P2 | AA |
| 35 | Thu 9/10 | G | G4 | QA: Validate transcription accuracy and memo compliance | P2 | QA |
| 36 | Thu 9/10 | H | H1 | Build regression model for next-month travel spend forecast | P2 | DA |
| 37 | Thu 9/10 | H | H2 | Surface spending forecast on dashboard | P2 | DA |
| 38 | Thu 9/10 | H | H3 | QA: Sanity-check forecast against historical trend | P2 | QA |
| 39 | Thu 9/10 | I | I1 | Build "Syndicated Spending" clustering model | P2 | DA |
| 40 | Thu 9/10 | I | I2 | Surface fraud clusters on dashboard | P2 | DA |
| 41 | Thu 9/10 | I | I3 | QA: Validate clustering doesn't false-positive on legitimate shared expenses | P2 | QA |
| 42 | Thu 9/10 | J | J1 | Build natural-language Q&A over dashboard data | P2 | DA |
| 43 | Thu 9/10 | J | J2 | QA: Test Q&A against a question bank | P2 | QA |
| 44 | Thu 9/10 | E | E6 | QA: Functional and UX testing of the dashboard | P0 | QA |
| 45 | Fri 9/11 | K | K1 | End-to-end pipeline test across full sample dataset | P0 | QA |
| 46 | Fri 9/11 | K | K2 | Edge case pass: duplicates, split-receipting, bad input | P1 | QA |
| 47 | Fri 9/11 | K | K3 | Amara-scrutiny review pass | P1 | PM |
| 48 | Fri 9/11 | A | A5 | Finalize Governance & Documentation deliverable | P0 | PM |
| 49 | Fri 9/11 | K | K4 | Demo script & backup recording | P0 | PM |
| 50 | Fri 9/11 | K | K5 | Sprint retro & scope-cut log | P1 | PM |

---
