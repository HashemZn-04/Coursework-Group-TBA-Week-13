# Handoff 3 — the dashboard backlog: E3 built, E2 fixed, E4's queue bug found, H and I landed

Covers one working session (2026-09-09/10). Companion docs: `ticket_work/handoff.md`
and `ticket_work/handoff_2.md` (earlier sessions), `ticket_work/epic_3_tickets.md`
(the Epic C ticket guide).

**State at the end of this session:** `pytest -q` → **224 tests, green**, no
credentials and no network needed. Everything DA-owned that had no external
blocker is now built. Nothing is committed — the work is uncommitted in the
working tree, along with the earlier sessions' work.

---

## 1. What was asked for

Build E3 (the policy health trend view), and finish any other ticket that is not
waiting on somebody else. That turned into six tickets, plus one bug found on the
way that mattered more than any of them.

---

## 2. The bug nobody had written down: the review queue never emptied

`pages/2_Review_Queue.py` filtered on the verdict alone:

```python
queue = df[df["verdict"] == VERDICT_HIGH]
```

`record_decision` writes a Decisions row and updates `Receipts.status`. It never
touches the verdict — deliberately, because the engine's judgement is part of the
audit trail and Amara's decision does not retract it. So after Approve was
clicked, the page reran, the caches cleared, the sheet was re-read — and the
receipt was **still `high_risk`, so it was still in the queue.** Permanently.
Every decided receipt would accumulate there.

That fails E4's second acceptance clause outright — *"queue updates without a
full manual refresh"* — and it reads to the user as "the button did nothing",
which is precisely what the cache-clearing inside `record_decision` was written
to prevent. It would have shown up in the first ten seconds of the demo.

Nothing caught it because **no test touched a page**. Every one of the previous
104 tests targeted `api.*` or `dashboard.data`; the arithmetic underneath the
page was right and the page was wrong.

The queue now filters on what actually removes a receipt from it — a standing
decision — and `tests/test_pages.py` drives the real pages through
`streamlit.testing.v1`: seed the sheet, run the page, click the button, assert
what a reviewer would see. That file is the first page-level coverage in the
repo, and it is where the next bug of this shape will be caught.

---

## 3. E2 — the leakage tile measured the wrong thing

The AC asks for "a running total of leakage **prevented**". The tile summed
high-risk receipts, which is money **at risk**. A rejected claim is still a
high-risk claim, so the number could not move when Amara rejected anything: the
one figure on the dashboard meant to show the system paying for itself was
structurally incapable of changing.

Spend Overview now shows four tiles — **Claimed → Approved → At risk · awaiting
your decision → Leakage prevented** — with a caption saying in plain words that
only the last one is a saving, plus a running-total chart of prevented money
plotted on the date of the rejection.

Definitions that had to be pinned down, and why:

* **Prevented = receipts whose *current standing* decision is `rejected`.** The
  Decisions tab is append-only, so a receipt can carry several rows. Latest wins,
  matching how `load_expenses` already resolves multiple verdicts and how
  `record_decision` overwrites `status`. Any-rejection-counts would leave a
  reversed rejection in "prevented" for ever while the money was actually paid —
  and Amara's own described loop *is* reject → employee explains → approve.
* **Aggregate over receipts, never over decision rows.** A double-clicked Reject
  writes two rows; summing rows doubles the saving.
* **Decisions is the source of truth for money, `status` is display only.**
  `status` is overwritten in place, carries no history and no date, and is only
  written `if cell:` — a receipt whose row moved keeps a stale status while the
  decision lands correctly.

Two more bugs fixed on the same page:

* **Every total was prefixed `$`,** including GBP claims, and `groupby(category)`
  added USD to GBP. Totals are now grouped by currency, never summed across, and
  rendered through `api.summary.format_money` — the same function the Review
  Queue already used.
* **"Spend velocity" was not a velocity.** It plotted one point per receipt
  against its date and joined them with a line. On the live sheet seven receipts
  share the timestamp `08/20/10 13:12:01`, so seven points stacked on one x-value
  and the "line" was a vertical spike in arbitrary order. It is now spend per
  calendar bucket, bucket size chosen from the span, empty periods drawn as zero.

The banner about unprocessed receipts also contradicted the page it was on: it
said they were "missing from the figures above" while the total included them.
Resolved as *Claimed includes them, the outcome tiles do not* — and the buckets
are now a partition, asserted to the penny in `tests/test_spend.py`.

---

## 4. E3 — policy health, built

`pages/4_Policy_Health.py` and `dashboard/policy_health.py`. Two questions from
two sources, kept apart because they can be true at different times:

1. **Is the pipeline clearing claims, and is that changing?** From the Verdicts
   tab. Thin today, and thickens on its own when C3's gap closes.
2. **Which handbook rules are actually being broken?** Re-checked here against
   the receipts, so it needs no verdict and works on every row in the sheet now.

### The decision worth defending: the rules are recomputed, not read back

The flag codes the engine produces (`CFO_APPROVAL_THRESHOLD` and the rest) exist
in n8n's `combined_flags` and in `/api/audit`'s response, and are **thrown away at
persist time** — the Verdicts tab stores a verdict, a sentence and a timestamp.

Recovering them by matching the sentence was considered and rejected. On the path
we actually demo, the `reason` is the governance prompt's free text, which
contains no codes at all; where `build_summary` did write it, only the English
survives. That would give a chart whose completeness silently depended on which
code path wrote the row.

Adding a `flags` column to the Verdicts tab was the other option and was also
rejected, for this week: it changes shared write-path code, it needs AA to map a
column on a Verdicts append node that **does not exist yet**, and the chart ships
without it. Worth doing when AA builds that node — it is the cheapest moment,
because there is nothing to migrate.

So the rules are re-derived from the receipt rows, and the page says so on its
face, including what that costs: it sees the deterministic layer and C4 and
nothing else, so it **under-counts** — the AI's contextual risk factors are not
recoverable from the sheet.

### What is on the page

* Four tiles: assessed, cleared-without-a-human, needs-a-decision, and the share
  coded **Miscellaneous** — Amara's most-repeated complaint ("it used to be this,
  like, our most common category, and it should be our rarest by miles") and on
  no page anywhere until now.
* A stacked count of verdict states per calendar month, plus the same table with
  a clearance rate per month. Counts rather than a 100%-stack deliberately: a
  normalised stack makes a month holding one receipt look as substantial as a
  month holding two hundred.
* Most-broken rules, ranked by count, with each rule's **own** base beside it —
  seven of the twelve categories have no numeric ceiling, so a travel claim
  belongs in no category-limit fraction at all.
* The policy-decay count: claims over the written figure but inside the same
  figure restated in today's money. That is the brief's own Policy Decay problem
  measured, and it is what separates "our people got worse" from "our rules got
  older".
* Breakdowns by category and by submitter.

### Three choices that were not obvious

* **The trend buckets on `receipt_date`, not the verdict's `created_at`.** The
  day C3's gap closes and seven backlog receipts are audited at once, a
  `created_at` trend would draw our own deployment as a compliance event. It also
  keeps this page and Spend Overview clocking the same receipt the same way.
* **Only months containing receipts are drawn.** The live span is 192 months with
  two populated; reindexing across it produces a chart that is 99% whitespace.
  When the populated months are too few or too far apart, the chart is still
  drawn — the AC asks for one — with a warning that it is a composition, not a
  trend.
* **No percentage is shown over fewer than five assessed receipts.** That floor
  is ours; nothing in the handbook or the interview sets a materiality threshold,
  and the page says so.

Unassessed receipts are their own red state on the chart and are excluded from
the numerator **and** denominator of every rate. Folding them into a compliance
denominator would render a pipeline outage as a compliance collapse — the wrong
diagnosis, and it would send someone to fix the wrong thing.

---

## 5. H1 / H2 — the travel forecast, and what it refuses to do

`api/forecast.py` + `dashboard/forecast_view.py`, surfaced as a section of Spend
Overview (which is what the ticket itself suggests: "a forecast line alongside
actual spend in E2").

**The honest headline: on the live sheet it refuses, by name.** There is one
travel receipt and it has no verdict. Ordinary least squares over
`sklearn.linear_model.LinearRegression` needs a history that does not exist yet.
Amara's stated bar is a tool that fails fast and clearly rather than one that
makes her wait and then tells her nothing, so the module returns a reason code
and a sentence instead of a number: `TRAVEL_SPEND_UNPROCESSED`,
`NO_TRAVEL_SPEND`, `TOO_FEW_MONTHS`, `MIXED_CURRENCY_HISTORY`, `SPAN_TOO_WIDE`,
`NO_READABLE_TOTALS`. `python scripts/h1_demo.py` walks every one of them.

Four decisions inside it:

* **A month with no travel claims is a real zero; a month whose travel claims
  were never audited is not.** Censored months are excluded from the fit and
  named, not zero-filled. This is invariant 1 applied to a time series, and on
  the live sheet it is the dominant case rather than an edge case.
* **Inflation is a comparator, not a term in the model.** The World Bank series
  is annual and about a year in arrears; folding ~3% into a fit over a handful of
  monthly points would be swamped by noise while implying precision that is not
  there. It uprates the trailing average instead, which is what separates "spend
  is rising" from "prices are rising". It is passed in, so the module makes no
  network call.
* **The range cannot collapse.** A perfectly linear history has zero residual
  spread, and a declining one clamps the forecast to zero; either would print a
  zero-width interval to a CFO as certainty. The half-width widens with the
  horizon and is floored against the larger of the forecast and the trailing
  average.
* **The trailing three-month mean is returned alongside**, because QA's H3 ticket
  compares the model against exactly that, and making them derive it invites two
  different numbers.

---

## 6. I1 / I2 — patterns of concern

`api/clusters.py` + `pages/5_Patterns_of_Concern.py`, with a new **Cluster
Reviews** tab for I2's "mark a cluster as reviewed".

Amara described two patterns and they are not the same shape — syndicated ("are
they passing this around between them", several employees each claiming part of
one expense) and duplicate ("a way to look back at other ones submitted by the
same person"). Both come out of the same grouping, so this finds groups once and
labels each by how many people are in it.

**The similarity is defined by hand; only the grouping is learned.** The AC asks
for a *documented* similarity basis, and a centroid is not one. So the distance
between two claims is defined in named units — how far apart the amounts are as a
share of the tolerance, how many days apart as a share of the window — and
`DBSCAN` with that precomputed distance does the grouping. Chosen over KMeans
because it needs no `k`, groups transitively, and is allowed to leave a claim in
no group at all, which is the answer for most claims.

**The live sheet is the demo, and it is real data:** seven near-identical
WAL\*MART claims dated the same day across two submitters, spelled `WAL*MART`,
`WAL-MART` and `Walmart`. It groups them, names the exact repeats per person, and
says out loud that the thresholds behind the judgement are GBP while the claims
are USD.

**What stops it crying wolf** — QA's I3 ticket is specifically about this, so it
was written against I3 in advance (`python scripts/i1_demo.py` runs those cases):

* Same merchant and same currency only, after normalisation. A name that reduces
  to nothing matches nothing, rather than matching every other unreadable receipt.
* Dates within a few days — Handbook 10.2's concern is same-date clustering, so a
  team legitimately using one vendor month after month does not group.
* A group only reaches the review list when something makes it worth the time: an
  exact repeat by one person, a material amount, or claiming on more than one
  date. Two colleagues buying coffee at the same place on the same morning meets
  none of those and is listed below a materiality floor rather than hidden — a
  guard you cannot see is a guard nobody can check.

**The review is keyed to the exact set of claims reviewed**, not to a generated
cluster id. The cluster is recomputed on every page load and has no stable
identity; if the group later gains a claim, the key changes and it reappears —
which is right, because Amara cleared a different set.

---

## 7. Also fixed, in the layer underneath

* **A tz-aware/tz-naive crash waiting to happen.** `receipt_date` parses
  tz-naive; `created_at` on every n8n row is Zulu. Subtracting them raises
  `TypeError`, and that subtraction is the one-month cutoff — the rule that
  produces most of the live sheet's rule breaches. `_parse_timestamps` now puts
  both on one clock.
* **An empty sheet returned a frame without its derived columns**, which made
  every caller's `.empty` check load-bearing: forget one and it is a `KeyError`
  on `date` or `total` exactly when the sheet is empty, which is a fresh
  deployment. It now returns the columns.
* `latest_decisions` sorts with missing values **first** on both keys, so an
  undated, unnumbered hand-edited row cannot overrule a properly recorded
  decision. pandas' default would have let it win every tie.

---

## 8. What is still blocked, and on what

| Ticket | Blocked on | Inside this repo? |
|---|---|---|
| C3, C5 | AA's n8n punch list (`epic_3_tickets.md`) — no receipt from the real Slack path gets a stored verdict until it lands | No — another person |
| A4 | QA's A6 labelled test set, which does not exist anywhere | No — another person |
| J1 (agentic Q&A) | An LLM API key. There is none in the project: `.env.example` says so, `openai` is in requirements but imported by nothing | No — a credential |
| B3 (reopened) | Mason's five missing fields (`justification`, `approval_reference`, `attendee_count`, `employee_home_office`, `journey_duration`) and the undeclared drop of `source_channel`. Adding columns needs AA to remap the n8n Sheets node and PM to re-broadcast | Partly — needs the team |
| D1 | The state-machine artifact is not in this repo. Two teammates asked for a clarification state and the codebase then went the other way, removing the only tier that could have held it | No — needs a decision |

**H1/H2 are built but cannot be *demonstrated* on live data** until travel claims
accumulate and get verdicts. That is a data dependency, not a code one, and the
demo script covers the ticket in the meantime.

---

## 9. What to do next, in order

1. **Commit this work.** Three sessions of it are uncommitted.
2. **Run the dashboard against the real sheet** — `streamlit run streamlit_app.py`.
   Still nothing has been seen in a browser. The page tests exercise every page,
   but they are not a substitute for looking at it.
3. **Send AA the C3 punch list.** Unchanged, and still the one thing gating C3
   and C5 end to end.
4. **Paste `api/governance_prompt.py`'s `SYSTEM_PROMPT` into n8n** — both copies —
   and get Alex's sign-off. Two known content fixes are still unapplied: it says
   `$2,000`/`$250` where the handbook is GBP, and it does not cover Miscellaneous
   at all, which is one of the brief's five headline problems and Amara's
   specific complaint.
5. **Capture the acceptance evidence:** `python scripts/c4_demo.py`,
   `python scripts/h1_demo.py`, `python scripts/i1_demo.py` into MCP-27, H1 and I1.
6. **Answer Mason and Alex on D1** — the clarification state, what triggers
   escalation, and flagged-vs-high-risk. Two people are waiting, and the
   "two outcomes, not three" call needs defending or reversing, not ignoring.
7. **When AA builds the Verdicts append node, add a `flags` column to it** — that
   is the moment the Policy Health rules chart can stop under-counting, and the
   moment it costs nothing to add.

---

## 10. Tested vs. not

**Tested:** 224 pytest tests — the audit engine, policy limits, summary
generation, every API endpoint, the CPI sheet writer, the dashboard data layer,
the spend/leakage arithmetic, the policy-health aggregations, the forecast model,
the clustering model, and — new this session — **every Streamlit page driven end
to end** through `streamlit.testing.v1`, including clicking Approve and Reject
and asserting the queue empties. No credentials, no network; an autouse fixture
refuses live sheet access and the inflation series is stubbed.

**Not tested:** nothing has been seen in a running browser session; no live n8n
execution; no OpenAI call from Python; and neither stretch model has ever run
against enough real data to produce a number worth acting on — the forecast
refuses on the live sheet by design, and the only cluster the live sheet yields
is a genuine one, but it is a genuine one in test data.
