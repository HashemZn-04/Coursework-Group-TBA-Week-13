Project Brief: Autonomous Expense Intelligence
Problem Statement

In most modern organisations, expense management remains one of the final frontiers of manual administrative friction. While sales and product development have shifted to real-time data, finance departments often rely on a "retrospective" model. Employees collect physical or digital receipts over a month, manually categorise them into legacy ERP systems, and submit them in batches.

As a result, CFOs and finance leadership operate under a permanent data lag.

Significant issues arise from this lack of transparency:

    The "Miscellaneous" Trap - Without intelligent categorisation, a high percentage of spend is dumped into generic buckets, masking waste or systemic overspending on non-essential services.
    Shadow Spending - Employees often bypass procurement protocols for "small" items that add up to massive, unmanaged costs across the organisation.
    Audit Bottlenecks - Finance teams spend hundreds of hours performing "low-value" audits - manually checking dates and amounts - instead of focusing on high-level forensic analysis or tax optimisation.
    Policy Decay - Internal spending limits often fail to track with real-world economic volatility. In a high-inflation environment, static rules become either unfairly restrictive or dangerously loose.
    Fraud and Duplication - Human auditors struggle to catch "split-receipting" or duplicate claims submitted across different months.

There is currently no bridge between the CFO's intent (governance rules) and execution at the receipt level. Business rules are often trapped in unread PDF handbooks that systems cannot enforce.
Elevator Pitch

You'll be working with a CFO/Head of Finance as your Stakeholder, building an expense platform bespoke to the problems that they face.
Stakeholder
Amara Osei
Head of Finance

Amara has been Head of Finance at Meridian Consulting Group for three years. In that time, the firm has grown from 120 to 380 employees, and the expense management system that worked for a small team has become a genuine operational liability. She inherited a policy handbook last updated in 2019, a finance team that spends two weeks every month processing expenses, and a CEO who keeps asking why the monthly close takes so long.

She is not interested in another off-the-shelf SaaS product. She has evaluated four of them. None of them let her define her own rules, and none of them integrate with the firm's existing Slack-based workflows. What she wants is a system that thinks the way a good finance analyst thinks - catching the things a senior auditor would catch, flagging the things that need a human decision, and leaving a paper trail that auditors can follow.

She is technically literate enough to understand what you build, and demanding enough to push back if it does not actually solve the problem.
Data Sources

What data sources will you use? How will you access them? How often do they update?

    Stakeholder Requirements - Qualitative data gathered from structured, live interviews with the CFO to define "Acceptable Spend" and "Risk Thresholds."
    Receipt Ingest - User-submitted images (JPG/PNG) and digital invoices (PDF) captured via an agreed input method.
    Market Intelligence - Real-time 2026 Consumer Price Index (CPI) data or travel benchmark APIs to validate "Fair Market Value."

Proposed Solution & Functionality

The project consists of an end-to-end intelligence layer that automates the "Decision Logic" of a senior financial auditor:
Requirement Discovery

The team will meet with the CFO to extract specific, often unspoken, business rules. These are then codified into an AI Governance Prompt that acts as the "brain" of the auditor.
Zero-Touch Ingestion

    Trigger - A Slack channel and/or dedicated email for incoming receipts.
    Vision Extraction - Uses AI to perform high-fidelity OCR, extracting line items, tax, merchant details, and dates.

The Intelligent Audit

    Policy Match - The AI compares the receipt against the CFO's rules (for example, "Is this an unapproved software subscription?").
    Contextual Validation - The system checks 2026 economic data to determine if a claim is a "Good Deal" or a "Policy Violation" based on current inflation.

Human-in-the-Loop Workflow

If the AI detects a "High-Risk" anomaly, it generates a natural-language summary and routes it to the CFO's dashboard for 1-click approval or rejection.
Data Analysis

All approved expenses should be queryable on a dashboard.
Planned Outputs

List the user-facing outputs of your project:

    The "CFO Eyes" Dashboard - An interface showing real-time spend velocity, identified "Leakage" (money saved), and policy health trends.
    Slackbot - An interface for employees to submit expenses and receive instant compliance feedback.
    Governance & Documentation - Structured documentation of the CFO's requirements translated into technical "Rules of Play" used by the AI.

Deadlines

Is this project possible to complete within one week for a team of 3-5 people? Yes.
Data

Your primary data will come from the stakeholder interview and the receipt ingest process. Sample expense data will be provided by your facilitator.
Stretch Goals

    Voice-to-Memo - Allow employees to explain a "missing receipt" via voice note, which the AI converts into a compliant memo.
    Predictive Spending - Use a simple regression model to forecast the next month's travel spend based on current 2026 price volatility.
    Fraud Clustering - Identify "Syndicated Spending" - groups of employees consistently submitting similar "non-flagged" expenses.
    Agentic Interface - The dashboard should allow for agentic, natural language questioning.

