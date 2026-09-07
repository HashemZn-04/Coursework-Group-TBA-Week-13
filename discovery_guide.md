# Discovery Guide — Monday 2026-09-07

This is what all 4 of us do **today**, together. Today is entirely Day 1 of the 5-day plan in `suggested_workflow.md` — it's a discovery and setup day, not a build day. Nothing gets "built for real" yet; the goal is to leave today with a locked foundation everyone can build on starting tomorrow.

By end of day, we should all be able to check off:
- [ ] Receipt data schema locked and agreed by all 4 of us
- [ ] Jira backlog fully imported from `tickets.md`, with owners assigned
- [ ] Stakeholder interview with Amara completed (or, if she's genuinely unavailable today, firmly scheduled for first thing tomorrow — this is the one thing that can't slip past Tuesday morning without pushing the whole week)
- [ ] n8n instance running with a working Slack trigger skeleton
- [ ] Database schema drafted
- [ ] Streamlit app shell running (even with fake data)

---

## Morning: Whole-Team Kickoff (do this first, together)

1. **Read the project brief together**, out loud if useful — make sure everyone has the same mental model of the problem (the "Miscellaneous Trap," shadow spending, audit bottlenecks, policy decay, fraud/duplication) before splitting up.
2. **Walk through `suggested_workflow.md`** — confirm everyone understands their role's primary ownership and where it overlaps with others.
3. **Set a mid-day check-in time** and an end-of-day check-in time. Today has more dependencies between roles than any other day this week, so don't disappear into silos until each other's outputs are ready.
4. **Agree on the receipt data schema together** (this is the single most important thing to lock today — see the Data Analyst section below for the proposal to react to).

---

## Project Manager — today's checklist

1. **Prepare interview questions for Amara** before the interview, pulling directly from the brief. At minimum, get concrete answers on:
   - Spend thresholds by category (what's the dollar line for "needs approval"?)
   - The unapproved-vendor / unapproved-software list (or how she currently decides this)
   - Travel policy specifics (what counts as fair market value, what's excessive)
   - What she currently checks manually that a senior auditor would catch (this is where the "unspoken rules" live)
   - What "split-receipting" looks like in practice, from cases she's actually seen
2. **Conduct the interview.** Capture verbatim quotes, not paraphrases — they surface unstated rules better and give the team something concrete to cite in the Rules of Play doc. (Ticket A1)
3. **Set up the Jira project** and import the full backlog from `tickets.md` — one epic per epic heading, one issue per ticket, priorities as given. Assign initial owners using the Execution Order table at the top of `tickets.md`.
4. **Start drafting the "Rules of Play" doc** (Ticket A2) from your interview notes — doesn't need to be finished today, but get the structure down and the first few rules written while the interview is fresh.
5. **If time allows:** sketch the approval/rejection state machine (Ticket D1) — pending → approved/rejected → escalated, and what triggers each transition. A quick whiteboard/diagram is enough for today.

## Data Analyst — today's checklist

1. **Propose the receipt data schema first thing** — this blocks the Automation Analyst and everyone downstream, so get a draft in front of the team early, not at 4pm. At minimum: merchant, date, line items, tax, total, currency, submitter, source channel, raw file reference. Bring it to the whole-team kickoff for sign-off. (Ticket B3)
2. **Design the database schema** for receipts, extracted line items, policy verdicts, approvals, and the audit trail — this needs to support reconstructing, for any receipt, what was submitted, what was decided, why, and what the human did about it. (Ticket C1)
3. **Stand up the Streamlit app shell** with basic navigation (spend overview / review queue / expense browser as separate pages), pointed at mock data for now. (Ticket E1)
4. **Sync with PM** on the approve/reject state machine sketch (Ticket D1) if PM gets to it today — you'll be implementing it tomorrow/Wednesday.

## Automation Analyst — today's checklist

1. **Stand up the n8n instance** (self-hosted or the free n8n Cloud tier — whichever the team can get running fastest today).
2. **Build the skeleton ingestion workflow**: a native Slack Trigger node watching a dedicated receipt-submission channel, confirmed to fire on file upload (even if it just logs the payload for now). (Ticket B1)
3. **Set up the dedicated Slack channel/app** for receipt submissions if it doesn't exist yet.
4. **Review the Data Analyst's draft receipt schema** as soon as it's proposed — flag anything the extraction step won't realistically be able to produce (e.g. a field OCR can't reliably read) before it gets locked.

## Quality Assurance — today's checklist

1. **Draft the structure for the labeled governance test set** — decide what a labeled example needs to contain (input receipt, expected verdict, expected reasoning, which Rule of Play it maps to) so it's ready to fill in with real examples once the Rules of Play doc exists. (Ticket A6)
2. **Review the Data Analyst's draft receipt schema for testability** before it's locked — flag anything ambiguous, anything that can't be verified automatically, or any field that's missing and will bite us later.
3. **Set up Jira issue conventions for bugs/defects** (issue type, labels, whatever the team needs) so when QA starts finding problems from Tuesday onward, they land in the same place as the backlog rather than a side channel.
4. **Sit in on the stakeholder interview if possible** — hearing Amara's actual concerns firsthand makes it much easier to write realistic test cases later instead of working secondhand from notes.

---

## End of Day: Whole-Team Check-In

Before anyone logs off today, confirm out loud as a group:
- Is the receipt schema actually locked, or does it just feel locked? (If anyone still has an open question about it, resolve it now — not tomorrow morning.)
- Did the interview happen? If not, is it firmly on the calendar for tomorrow morning, and does that change tomorrow's plan?
- Is Jira actually usable — can everyone see their assigned tickets for tomorrow?
- Any blocker found today that changes how we should sequence tomorrow (Tuesday)?

Tomorrow (Tuesday 2026-09-08) is the start of core pipeline build — see the "Day 2" section of `suggested_workflow.md` and rows 9-15 of the Execution Order table in `tickets.md`.
