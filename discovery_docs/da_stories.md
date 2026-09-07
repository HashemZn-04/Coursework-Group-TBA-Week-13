# DA Stories: Autonomous Expense Intelligence

Scope: tickets where the Data Analyst (DA) is sole owner, or main co-owner (DA listed before the other role in the Execution Order table, e.g. "DA + AA"). Tickets where DA is listed second (e.g. "AA + DA", such as B6) are excluded.

Priority uses the Jira scale (Highest, High, Medium, Low, Lowest), mapped from the tickets doc as: P0 = Highest, P1 = High, P2 = Medium/Low/Lowest based on the documented stretch-goal cut order (Predictive Spending cut last among DA's P2 work, Fraud Clustering next, Agentic Interface cut first).

---

## B3. Define shared receipt data schema

**Description:** Agree on the structured object every part of the system uses for a receipt: merchant, date, line items, tax, total, currency, submitter, source channel, raw file reference.

**User story:** As the Data Analyst, I want one agreed receipt schema, so that n8n workflows, the audit engine, and the dashboard all read and write the same data shape.

**Acceptance criteria:** Schema documented and agreed by all four roles before Day 2 build starts. Any change after that point is communicated to the whole team via PM.

**Dependencies:** None (foundational).

**Priority:** Highest
**T-shirt size:** S
**Due date:** Mon 2026-09-07

---

## C1. Design database schema for receipts, verdicts, and audit trail

**Description:** Model receipts, line items, policy verdicts, approval/rejection decisions, and timestamps so every decision can be traced end to end.

**User story:** As Amara, I want a full audit trail stored for every receipt, so that I can see what was submitted, what the AI decided, why, and what the human did about it.

**Acceptance criteria:** Schema supports reconstructing, for any receipt, what was submitted, what the AI decided, why, and what the human did about it.

**Dependencies:** B3 (receipt schema), D1 (approval/rejection state machine).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Mon 2026-09-07

---

## E1. Build dashboard shell & navigation

**Description:** Stand up the Streamlit app skeleton with separate pages for spend overview, review queue, and expense browser.

**User story:** As Amara, I want a working dashboard shell, so that I have one place to check spend, review flags, and browse expenses.

**Acceptance criteria:** Navigable Streamlit app runnable locally (and deployable free on Streamlit Community Cloud), pointed at mock data initially.

**Dependencies:** None.

**Priority:** Highest
**T-shirt size:** S
**Due date:** Mon 2026-09-07

---

## A3. Build v1 of the AI Governance Prompt

**Description:** Turn the Rules of Play into a prompt/config the audit engine calls per receipt to get a policy verdict and reasoning. DA owns how the rules are encoded; PM signs off that it matches what Amara asked for.

**User story:** As the audit engine, I want a governance prompt that checks a receipt against Amara's rules, so that I return a verdict and reason automatically.

**Acceptance criteria:** Prompt takes a structured receipt object as input and returns a structured verdict (compliant / flagged / high-risk) with a natural-language reason. Tested against at least 5 sample receipts spanning compliant, borderline, and violating cases. PM has signed off the mapping against the Rules of Play.

**Dependencies:** A1 (stakeholder interview), A2 (Rules of Play doc), B3 (receipt schema, for the input/output contract).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Tue 2026-09-08

---

## C3. Implement Policy Match against Governance Prompt

**Description:** Build the audit API that the extraction workflow calls with each incoming receipt. It calls the Governance Prompt and saves the verdict using the C1 schema.

**User story:** As the system, I want to automatically check every receipt against policy, so that flagged and compliant receipts are recorded without manual review.

**Acceptance criteria:** Every ingested receipt receives a stored policy verdict (compliant / flagged / high-risk) with reasoning text, within a few seconds.

**Dependencies:** A3 (Governance Prompt), C1 (database schema).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## C4. Implement Contextual Validation (inflation-aware)

**Description:** Combine CPI/benchmark data with the receipt amount to flag a "Good Deal" vs a "Policy Violation" based on current economic conditions, not a static limit.

**User story:** As Amara, I want spend judged against current inflation, so that fair prices are not wrongly flagged and outdated limits do not let bad spend through.

**Acceptance criteria:** A receipt priced above a static old limit but within the current inflation-adjusted benchmark is correctly classified as acceptable (and vice versa), shown with at least one constructed example.

**Dependencies:** C2 (CPI/market intelligence pull), C1 (database schema).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## C5. Build High-Risk routing & natural-language summary generation

**Description:** When a receipt is judged high-risk, generate a plain-language summary as part of the API response so it can be posted to Slack and shown on the dashboard queue.

**User story:** As Amara, I want a plain-language summary of any high-risk receipt, so that I can quickly understand what was flagged and why.

**Acceptance criteria:** A high-risk receipt produces a human-readable summary (what was flagged, why, amount, submitter), delivered to Slack via n8n and available to the dashboard via an API.

**Dependencies:** C3 (Policy Match), C4 (Contextual Validation).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## C6. Expose approved-expense query API for dashboard

**Description:** Build the API/query layer the dashboard uses to fetch approved expenses, filterable by date range, category, employee, and amount.

**User story:** As Amara, I want to query all approved expenses from the dashboard, so that I can analyze spend without needing direct database access.

**Acceptance criteria:** Dashboard can retrieve filtered/paginated approved expense data without needing direct DB access.

**Dependencies:** C1 (database schema), C3 and C4 (verdicts that determine what counts as approved).

**Priority:** Highest
**T-shirt size:** S
**Due date:** Wed 2026-09-09

---

## D2. Build 1-click approve/reject API

**Description:** Build the backend endpoints the dashboard calls to record Amara's decision on a flagged receipt, updating the audit trail.

**User story:** As Amara, I want to approve or reject a flagged receipt in one click, so that my decision is recorded instantly and correctly.

**Acceptance criteria:** Approving or rejecting a flagged receipt from the dashboard updates its stored state and is reflected in the audit trail with timestamp and decision-maker.

**Dependencies:** D1 (approval/rejection state machine), C1 (database schema).

**Priority:** Highest
**T-shirt size:** S
**Due date:** Wed 2026-09-09

---

## E2. Build spend velocity & leakage visualizations

**Description:** Build near-real-time charts showing spend velocity and leakage (money saved via flags/rejections), sourced from real backend data.

**User story:** As Amara, I want to see spend velocity and money saved from flags, so that I can track the system's financial impact in real time.

**Acceptance criteria:** Dashboard shows at least: total spend over time, spend by category, and a running total of leakage prevented, sourced from real backend data.

**Dependencies:** C6 (approved-expense query API), C5 (high-risk/leakage data).

**Priority:** High
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## E3. Build policy health trend view

**Description:** Build a visualization of policy compliance trends over time, such as percent flagged over time and most-violated rules.

**User story:** As Amara, I want to see how policy compliance is trending, so that I can spot recurring problem areas.

**Acceptance criteria:** At least one chart showing compliance rate or violation breakdown trending over the sample data's time range.

**Dependencies:** C6 (query API), C3 and C4 (verdict data).

**Priority:** High
**T-shirt size:** S
**Due date:** Wed 2026-09-09

---

## E4. Build High-Risk review queue with 1-click approve/reject

**Description:** Build the dashboard view that shows high-risk summaries and lets Amara approve or reject them via buttons that call the approval API.

**User story:** As Amara, I want to review and act on high-risk receipts from one queue, so that I can clear flags quickly without leaving the dashboard.

**Acceptance criteria:** Amara-persona user can view a flagged receipt's summary and approve/reject it in one click from the dashboard; queue updates without a full manual refresh.

**Dependencies:** C5 (high-risk summaries), D2 (approve/reject API).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## E5. Build queryable expense browser

**Description:** Build a searchable and filterable table of all approved expenses using Streamlit's dataframe and filter widgets.

**User story:** As Amara, I want to search and filter all approved expenses, so that I can dig into spend by date, category, employee, or amount.

**Acceptance criteria:** User can filter by date range, category, employee, and amount, and results update accordingly.

**Dependencies:** C6 (approved-expense query API).

**Priority:** Highest
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## A4. Iterate Governance Prompt against real sample data

**Description:** Run the Governance Prompt against the facilitator-provided sample expense dataset and tune it for false positives/negatives using QA's labeled test set.

**User story:** As the Data Analyst, I want to tune the governance prompt on real sample data, so that it correctly matches Amara's actual rules, not just the cases we first wrote it against.

**Acceptance criteria:** False-positive and false-negative cases logged with example receipts; prompt revised at least once based on QA's findings; revision rationale documented.

**Dependencies:** A3 (Governance Prompt v1), A6 (QA labeled test set).

**Priority:** High
**T-shirt size:** M
**Due date:** Wed 2026-09-09

---

## H1. Build regression model for next-month travel spend forecast

**Description:** Use scikit-learn to build a simple regression model forecasting next month's travel spend, based on historical spend data and current 2026 price volatility.

**User story:** As Amara, I want a forecast of next month's travel spend, so that I can plan budgets ahead of time instead of reacting after the fact.

**Acceptance criteria:** Model trained on available sample/historical travel spend data produces a next-month forecast with a documented method (even a simple linear/polynomial regression) and a sanity-checked output range.

**Dependencies:** C6 (historical approved-spend data), C2 (2026 price/CPI data).

**Priority:** Medium
**T-shirt size:** M
**Due date:** Thu 2026-09-10

---

## H2. Surface spending forecast on dashboard

**Description:** Expose the regression forecast via API and show it on the dashboard, such as a forecast line alongside actual spend.

**User story:** As Amara, I want to see the spend forecast next to actual historical spend on the dashboard, so that I can compare prediction against reality at a glance.

**Acceptance criteria:** Dashboard shows a forecasted next-month travel spend figure alongside historical actuals, sourced from the model output.

**Dependencies:** H1 (forecast model).

**Priority:** Medium
**T-shirt size:** S
**Due date:** Thu 2026-09-10

---

## I1. Build "Syndicated Spending" clustering model

**Description:** Use scikit-learn (e.g. KMeans/DBSCAN) to find groups of employees consistently submitting similar non-flagged expenses, a pattern individual-receipt checks would miss.

**User story:** As Amara, I want the system to detect coordinated spending patterns across employees, so that I can catch fraud that individual receipt checks would miss.

**Acceptance criteria:** Model runs against the sample expense dataset and produces at least one identifiable cluster with a documented similarity basis (e.g. same vendor, similar amount, overlapping timeframe, across multiple employees).

**Dependencies:** C6 (approved-expense data), C1 (database schema).

**Priority:** Low
**T-shirt size:** M
**Due date:** Thu 2026-09-10

---

## I2. Surface fraud clusters on dashboard

**Description:** Show the clustering model's output as a reviewable list/view on the dashboard, separate from the individual-receipt review queue.

**User story:** As Amara, I want to review detected spending clusters on the dashboard, so that I can decide if a pattern needs action.

**Acceptance criteria:** Dashboard shows detected clusters with the employees/receipts involved and the basis for flagging, and lets Amara mark a cluster as reviewed.

**Dependencies:** I1 (clustering model).

**Priority:** Low
**T-shirt size:** S
**Due date:** Thu 2026-09-10

---

## J1. Build natural-language Q&A over dashboard data

**Description:** Let Amara ask free-text questions in the dashboard and get an answer grounded in real backend data via a direct LLM call, not a hallucinated response.

**User story:** As Amara, I want to ask plain-language questions about spend, so that I can get quick answers without building a filter or chart myself.

**Acceptance criteria:** At least 3 distinct natural-language questions produce correct answers grounded in the actual stored expense data, with the system declining or caveating when it lacks the data to answer confidently.

**Dependencies:** C6 (approved-expense query API).

**Priority:** Lowest
**T-shirt size:** L
**Due date:** Thu 2026-09-10

---

## D1. Design approval/rejection state machine

**Description:** Define the lifecycle of a flagged receipt: pending, approved/rejected, and optionally escalated, plus what triggers each transition. Listed as PM-owned in the tickets doc, but DA does the implementation.

**User story:** As Amara, I want a clear, defined lifecycle for a flagged receipt, so that every decision path (approve, reject, escalate) is predictable and leads to the right action.

**Acceptance criteria:** State diagram or equivalent doc; every state has a defined trigger and resulting action (e.g. reject → n8n notifies submitter in Slack).

**Dependencies:** None (foundational).

**Priority:** Highest
**T-shirt size:** S
**Due date:** Mon 2026-09-07
