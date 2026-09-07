Week 5 Group Project

Deliverables

Discovery
Problem Summary
Jobs to be done
As-Is process map
ROI

Planning
To-Be workflow
Jira Backlog tickets

Ticket Standards
Must Include
Title
Description
User story (As a, I want, so that)
Acceptance Criteria
Dependencies (on previous tickets)
Priority
Assignee 
Due date
Ticket Types (For AI Implementations)
Spike tickets
Feature tickets
Fallback tickets


Automated Workflow Plan
Trigger - Slack channel or email for incoming receipts
AI scans receipt to extract relevant information
Line items
Tax Merchant Details
Dates
AI compares receipt information against CFO’s rules
The system compares information to 2026 economic data to determine if the claim is a Good Deal or Policy Violation based on current inflation.
If the AI detects a "High-Risk" anomaly, it generates a natural-language summary and routes it to the CFO's dashboard for 1-click approval or rejection.

Governance
Spike and fallbacks tickets
Testing AI reliability before deployment
Using confidence levels and thresholds after all agentic outputs
Comprehensive audit logging
Defined testing strategy with all edge cases
Upholding the confidentiality of any sensitive personal information


















Main questions
Current process & friction
Walk us through what happens today when an expense comes in — who touches it, in what order.
Where does the two weeks of monthly processing time actually go?
What's the single most frustrating part of the current process for you or your team?
Acceptable spend, in practice
What counts as unapproved or non-essential spend? Concrete examples, not just categories.
Are there hard limits — per category, per role, per transaction? Do they vary by seniority or department?
What's currently hiding in "Miscellaneous" that shouldn't be?
What's actually still enforced from the 2019 handbook, vs. quietly ignored?
Risk signals
What does "high-risk" mean to you in practice — an amount, a category, a pattern?
Have you caught split-receipting or duplicate claims before? What tipped you off?
Fair market value
How do you currently judge whether a claimed amount is reasonable?
Any CPI or travel-benchmark source you'd trust, or is that open for us to choose?
Slack workflow & systems
What does the Slack workflow look like today — a channel, DMs, an existing bot?
What ERP or finance system holds the source-of-truth data? Can we get access, or should we plan around the sample data only?
Dashboard — data & views
Beyond the per-receipt fields we'll capture by default (total, tax, merchant, date, line items, currency), what else would you want tracked or visible — e.g. employee, department, cost centre, project code, payment method?
Would you want to view or filter expenses by item type (train tickets, restaurants, hotels, etc.)? If so, which categories matter most to you?
The brief points to spend velocity, leakage, and policy health as headline views — does that match what you'd actually want to see first, or is there something else more useful?
Human-in-the-loop
When something's flagged, who needs to see it — just you, or others too?
What do you need in a flagged summary to make a confident one-click call?
Demo & success criteria
What would you need to see on Friday to call this a real answer to the problem, not a toy demo?
Logistics
Could you share the policy handbook today?
Is there anyone else on your team we should talk to?
What's the best way to reach you for follow-up questions mid-week?


Narrowed Questions
PM 

  1. Walk us through what happens today when an expense comes in — who touches it, in what order — and what's the single most frustrating or time-consuming part?
All of it is tedious; People are supposed to submit when they happen. In practice, people will delay submission, resulting in a messy pile of receipt with no information. Spending a lot of time discerning valid expenses. Highly manual process via emailing people responsible for receipts. If a receipt is older than a month we won’t pay it. 
Keep the 1 month window for to-be process.
  2. What counts as unapproved or non-essential spend — concrete examples, not just categories — and are there hard limits per category, role, or department?
Non-essential stuff: miscellaneous snacks, hotel room service, hotel upgrade.
Reasonable-ness judgement. 
  3. What's currently hiding in "Miscellaneous" that shouldn't be?
Currently it is anything the loggers are not bothered to enter. It currently is one of the most common when it should be one of the rarest. AI needs more informative classification.
The AI to accurately categorise (i.e. entertainment instead of miscellaneous)
  4. What's actually still enforced from the 2019 handbook vs. quietly ignored — and can you share the handbook with us today?
Highly outdated, has some missing data. Inflation has increased prices and they are no longer reflected in the handbook
  5. What would you need to see on Friday to call this a real answer to the problem?
A working version; put a receipt in one end and actually functions. Able to deal with varying receipt data completeness.

  DA

  6. What does "high-risk" mean to you in practice — an amount, a category, a pattern?
If someone is consistently going over the edge, that is part of the risk category. iF WE HAVE TIME TO ANALYSE THE TRENDS, WE DEFINITELY WANT TO.
  7. How do you currently judge whether a claimed amount is reasonable — what do you weigh beyond just the price?
We have set limits for specific meals, they don’t mind if they spend slightly more, is it roughly in the ball park. If it a foreign receipt, we care about the exchange rate. Limit relative to what they are doing, does it match the limit? Do we have similar things people are buying to give us an edge?
  8. When something's flagged, who needs to see it, and what do you need in that summary to make a confident one-click call?
Amara needs to see it, everything gets escalated to her. Alot of the time, it just needs to be a sentence, they need to explain the why and in that case, i can approve it and say fine. If the reason isn’t satisfying, i will go back and ask more detail?

  AA

  9. What does the Slack workflow look like today, and what system holds the source-of-truth expense data — can we get access to it?
Slack workflow looks unprofessional and unconventional. Manual message type.
Source-of-truth is mostly the outdated handbook with scattered documents. Handbook needs updated figures. 

  QA — closes on fraud specifics (1 question)

  10. Have you caught split-receipting or duplicate claims before and how did you find that?
There have been both instances caught with the help of greg (?), requires a lot of manual review and has no trigger unless someone finds the time. Needs more active review, through automation.
What rules? For duplicated entries, this will be detected by the AI via timestamp and person.
For split-receipting, this can be given through a prompt.


ROI questions (reserve — ask only if she wants to see one)
Open with: "Would an ROI estimate be something useful for you to see, or is the priority just the working system itself?" If yes, work through:
Roughly how many finance-team hours a month go into manual expense processing and audit? What's that time worth, roughly?
What's the total monthly or annual expense volume — number of claims and total spend?
Any existing sense of what percentage of spend is misclassified or sitting in "Miscellaneous"?
Any existing sense of the scale of shadow spend, even a rough guess?
Any known or estimated cost from duplicate or split-receipted claims caught in the past?
What did evaluating the four rejected SaaS tools cost — in money, and in your team's time?
Is there a target you're hoping for — e.g. a specific reduction in processing time or in unmanaged spend — we could measure against?

Meeting Notes
PM (Alex) — process, policy, and Friday bar
Walk us through today's process — who touches it, what's most frustrating?
Employees should submit expenses as they happen. In practice, they sit on them for weeks, then dump a messy pile with no detail.
Whoever picks up the pile manually unpacks it, emails employees for missing info, enters it by hand.
Existing fix: receipts older than 1 month are auto-rejected.
Follow-up asked: keep the 1-month rule as-is, or tighten it? Answer: keep it at 1 month, no exceptions. She's done being lenient.
What counts as unapproved/non-essential spend — concrete examples, hard limits?
Test is "did this help you do the job," not a category list.
Fine: train ticket, work-relevant newspaper, a client entertaining drink.
Not fine: personal snacks (her example: 300g of Skittles), an unexplained hotel upgrade to a honeymoon suite.
Reasonableness test: "does this look like something someone would legitimately do?"
What's hiding in "Miscellaneous"?
Not fraud — avoidance. People use it to skip deciding a real category.
Used to be the most common category; improved via reminder emails but still an issue.
Genuine edge case that stays in Miscellaneous: a cool bag bought at an airport to carry a client's perishable gift — valid, but doesn't fit any normal category.
What's still enforced from the 2019 handbook vs. ignored — can you share it?
Handbook is outdated, thresholds haven't kept pace with inflation.
CFO approval threshold is actually $2,000, not the $1,000 written in the handbook — currently only recorded on a Post-it note.
She'll send the handbook, flagged as broadly correct but not fully up to date.
What do you need to see Friday to call this real, not a toy demo?
A working end-to-end flow: submit a receipt, get a result.
Explicitly burned before: a past vendor's tool made her wait 30 minutes before failing and asking her to type it in manually anyway — net negative.
Bar: fail fast and clearly. Automating basic checks (missing date, missing info, unclear relevance) alone would already help.
DA (Hashem) — judgment logic and flagged-item review
How do you judge if a claimed amount is reasonable — what beyond price?
Set limits per meal type (dinner > breakfast allowance); pays up to the limit, never over.
For foreign receipts: exchange rate matters, but so does purchasing power — a price that looks high in raw currency can be normal locally.
Wants historical comparison ("this person always spends double") — currently impossible, records are month-to-month in a spreadsheet with no continuity.
When something's flagged, who sees it, what do you need for a confident one-click call?
Everything escalates to her — she's the sole approver, no delegation.
Usually resolved with one sentence from the employee explaining the anomaly (e.g. "last-minute booking, hence the price").
If the explanation satisfies her → approve. If not → she asks for more detail.
She considers this back-and-forth conversation itself unautomatable.
AA — current systems
What does your Slack workflow look like today, what holds source-of-truth data, can we get access?
No automation today — just people typing messages and emails back and forth.
Source of truth is the (outdated) handbook plus informal unwritten updates — no structured expense database to integrate with.
QA (Mason) — fraud specifics
Have you caught split-receipting or duplicate claims before, how did you find that?
Yes, but rarely — no time to focus on it, though it matters for integrity.
Duplicates: catches them by recognizing a receipt she's seen before from the same person, while manually going through a pile. No systematic check.
Split-receipting: harder — described as "are they passing this around between them," meaning multiple employees each submitting part of one shared expense, not one person splitting their own purchase.
No trigger exists today beyond someone getting suspicious and looking back manually.
Her direct quote: "if you can automate that, amazing, please automate that."
Follow-up asked: what rules would you use to find these? Answer: duplicates — compare against the same person's past submissions. Split-receipting — watch for patterns jumping out across people (same vendor, close timing, amounts that look like pieces of one whole).
Closing — business case
Would you expect an ROI justification for this?
Not a full cost-benefit model. Wants two numbers only: rough build/run cost, and rough time saved.
No expectation of headcount reduction — framed as a time-saved pitch, not a cost-cutting one.
Follow-up: how many finance team hours a month go to manual expense processing?
Roughly 4–5 days of team time a month, done by about 3 people, in small increments around other work.
Hundreds of receipts monthly, much worse around Christmas.
Some employees: one receipt every 6 months, 10-minute job. Others (salespeople): 30–40 receipts, expensing far more than expected.

