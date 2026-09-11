# Handoff 6 — forecast horizon, RMSE%, mock data at scale, and two dashboard bugs found after seeding

Covers one working session (2026-09-11), picking up directly from
`ticket_work/handoff_haiku_work.md`'s "Notes for Next Session" (the 3-month
forecast question, and whether RMSE should be a percentage). Companion docs:
`handoff.md` through `handoff_5.md`, `handoff_haiku_work.md`.

**State at the end of this session:** `pytest -q` → **211 passed, 1 skipped**
(same `test_schema_parity.py` skip as every prior session). Everything below
is committed, in two commits: `936b56a "fix formatting error and seed data"`
(forecast horizon, RMSE%, indicative-range layout, GBP date-axis fix, mock
data generator + copy updates) and `bbcb5fa "refactored on formatting and
improved site optimisaiton"` (the metric-truncation CSS fix and the Patterns
of Concern performance fix, both requested in a follow-up message after the
first round was screenshotted). Both commits were made by the user mid-session
from their own git client, not by me — check `git log` if that's surprising.
The live Receipts tab has been written to for real: **3000 new rows,
receipt_id 609–3608**, in addition to whatever the sheet held before.

---

## 1. What was asked for

**Round 1**, working from the Haiku handoff's screenshot and open questions:

1. The "Indicative range" metric on the forecast card was still displaying
   too wide to read.
2. RMSE should be shown as a percentage, not in the forecast's currency.
3. The "Leakage prevented, running total" chart's x-axis showed a bare time
   ("03 PM") instead of a date when GBP was selected.
4. Extend `scripts/seed_mock_data.py`: 1000 more receipts per currency (USD,
   GBP, EUR — 3000 total), randomly dated across 2024–2026, ~85% `low_risk`,
   ~2% `miscellaneous`, so there's enough history to widen the forecast
   window from 1 month to 3.

**Round 2**, after the user screenshotted the live (mobile, dark-theme)
dashboard following that seeding:

5. Several metric tiles across the dashboard were rendering with an ellipsis
   mid-value/mid-label (`3608 of ...`, `At risk · awaiting your ...`,
   `£372.07–£3,...`) — font too big for the box, no matter the layout fix
   from item 1.
6. Patterns of Concern had become slow to load after the 3000-row seed.

---

## 2. Forecast horizon: 1 month → 3 months

`api/forecast.py` — added `FORECAST_HORIZON_MONTHS = 3` and changed
`target = anchor + 1` to `target = anchor + FORECAST_HORIZON_MONTHS`. This
was the thing the Haiku session flagged as ambiguous and reverted after it
broke two tests. Read the user's second ask ("prediction window to be 3
months instead of 1 month", tied explicitly to "more accurate prediction
forecasting" from the extra history) as the single-horizon reading — the
model now targets 3 months past the anchor, not next month — rather than
"show 3 consecutive monthly forecasts". Did not re-confirm; this was the
second time the same request had been made and the phrasing had firmed up
(singular "window", sized 3 instead of 1).

Updated everything downstream that hardcoded "next month":

- `tests/test_forecast.py`: `test_a_rising_history_forecasts_the_month_after_the_anchor`
  → renamed `test_a_rising_history_forecasts_3_months_after_the_anchor`,
  expected `forecast_month`/`forecast` recomputed (`2026-07`→`2026-09`,
  `680.0`→`760.0`). `test_the_forecast_reaches_forward_from_today_not_from_the_last_data_point`
  similarly recomputed (`steps_ahead` `3`→`5`). Every other test in the file
  either doesn't assert on the horizon or holds regardless of its value —
  checked each one by hand rather than just running the suite and reacting to
  red.
- `dashboard/forecast_view.py`: subheader is now horizon-aware —
  `"Next month's"` only when `FORECAST_HORIZON_MONTHS == 1`, else
  `f"{FORECAST_HORIZON_MONTHS}-month-ahead"` — so it doesn't silently go
  stale if the constant changes again.
- Copy-only updates: `scripts/h1_demo.py`, `README.md` (three places),
  `streamlit_app.py`.

## 3. RMSE as a percentage

`api/forecast.py`'s `model` dict gained `rmse_pct` — RMSE divided by the mean
of the fitted months' spend, ×100, `None` if that mean is 0 (guarded, though
in practice `diagnostics["found"] == 0` would already have refused before
this point). The original `rmse` (currency units) is untouched, because
`scripts/h1_demo.py` still prints it — no reason to break a working demo
script for a display-only change. `dashboard/forecast_view.py`'s "Model RMSE"
tile now shows `rmse_pct` (`f"{model['rmse_pct']:.1f}%"`, `"—"` if `None`).

## 4. Indicative range layout + GBP date-axis

`dashboard/forecast_view.py`: the three forecast metrics were in one
`st.columns(3)` row. Moved "Indicative range" to its own full-width
`st.metric()` call below a `st.columns(2)` of just the point forecast and the
trailing-average baseline — a currency range (`"£1,229.08 – £2,574.32"`) is
long, and a third of the row was never going to be enough regardless of font
size. (This turned out to be necessary but not sufficient — see §7.)

`pages/1_Spend_Overview.py`, the "Leakage prevented, running total" chart:
root-caused the "03 PM" axis label. It wasn't a parsing bug — Vega-Lite picks
its temporal axis tick format automatically based on how wide the data's date
*domain* is, and GBP's rejected-claims domain happened to be narrow (as few
as one point), which its heuristic reads as "show time of day" rather than
"show a date". Fixed by forcing the axis format explicitly:
`axis=alt.Axis(format="%d %b %Y", labelAngle=-30)`. Confirmed live against
the actual sheet (one GBP rejection, dated 27 March 2026) — before the fix it
rendered as a bare time; after, `27 Mar 2026`.

## 5. Mock data: 3000 more receipts, 2024–2026

`scripts/seed_mock_data.py` gained a second, independent generation cohort
alongside the existing trend-based one (`generate_currency`, unchanged):

- `EXTRA_MONTHS` — every `YYYY-MM` from 2024-01 to 2026-12 (36 months).
- `generate_extra_random(currency, seed, count=1000)` — each receipt lands on
  a uniformly random month/day in that range (no trend, unlike the original
  cohort), category chosen from `EXTRA_CATEGORY_WEIGHTS` (2% miscellaneous,
  the rest split travel/accommodation/subsistence/client_entertainment), and
  verdict `low_risk` with probability `EXTRA_LOW_RISK_SHARE = 0.85`.
- `MISC_MERCHANTS` — a small per-currency merchant table for the
  `miscellaneous` category, which the original generator never produced at
  all (Amazon UK/WHSmith/Ryman/Post Office for GBP, etc.).
- `generate(seeds, extra_seeds, extra_count)` now composes both cohorts;
  `main()` gained `--extra-seed-{gbp,usd,eur}`, `--extra-count`,
  `--extra-only` (skip the trend cohort — what was actually run, since the
  live sheet already had it), and `--no-extra` (old behaviour, trend cohort
  only).

Dry-run confirmed the targets before writing anything (~83–85% low_risk,
~2% miscellaneous, dates spread 2024–2026 for all three currencies). Ran
`python scripts/seed_mock_data.py --extra-only` for real:
**wrote 3000 rows, receipt_id 609–3608**, appended via one `ws.append_rows`
call (RAW value-input, same reasoning as the original script — Sheets' smart
date detection silently swaps day/month on ambiguous `DD/MM/YYYY` strings
under `USER_ENTERED`).

## 6. Verifying all of the above against the real, running app

Installed `playwright` + a headless Chromium into `.venv` temporarily (no
`chromium-cli` or `claude-in-chrome` available in this environment), started
`streamlit run streamlit_app.py` locally against the live sheet (read-only
navigation — the only write was the deliberate seeding script run above), and
screenshotted:

- Spend Overview's forecast card: "Indicative range" full-width and readable,
  "Model RMSE" showing `18.1%` (pre-seed) / later `50.4%` (post-seed, see
  §8), subheader reading "3-month-ahead travel spend (GBP)".
- Leakage prevented running-total chart with GBP selected: x-axis reading
  `27 Mar 2026`, not a time.
- Policy Health and Expense Browser: no regressions, no console errors,
  "Coded Miscellaneous" still `0.XX%` (Haiku's 2-decimal fix from last
  session held).

Uninstalled `playwright`/`pyee`/`greenlet` from `.venv` afterward — not a
project dependency, not in `requirements.txt`, only needed for this
verification pass.

## 7. Round 2: metric text ellipsis, dashboard-wide

The screenshots the user sent after the seed (mobile, dark theme) showed
`3608 of ...`, `At risk · awaiting your ...`, and `£372.07–£3,...` — the
layout fix in §4 wasn't the mechanism. Traced it into Streamlit's own
frontend bundle
(`.venv/.../streamlit/static/static/js/Metric.LAm2OYum.js` and
`StreamlitMarkdown.*.js`): `st.metric`'s label/value `<p>` tags get
`white-space: nowrap` unconditionally, and a conditionally-applied
`overflow: hidden; text-overflow: ellipsis` once the rendered text is wider
than the metric's box — tuned for a handful of digits in a wide column, not
for `"3608 of 3608"` in a quarter of a 4-tile mobile row. Confirmed via
`getComputedStyle` on the actual rendered `<p>` before reproducing it: at a
width wide enough not to overflow, `text-overflow` read `clip`/`visible` (no
truncation); the ellipsis only appears once the text genuinely doesn't fit —
which a plain desktop-width screenshot won't show, hence needing to check at
both a 4-columns-still-side-by-side width (~700px) and phone width (~380px).

Added `dashboard/style.py` (`inject_responsive_metric_css()`), called at the
top of `pages/1_Spend_Overview.py` and `pages/4_Policy_Health.py` — the only
two pages that use `st.metric` (`dashboard/forecast_view.py`'s metrics render
inside Spend Overview, so one call there covers it). The CSS:

- `container-type: inline-size` on `[data-testid="stMetric"]`, so `cqw`
  units in its children scale to *that metric's own box width*, not the
  viewport — a quarter-width tile in a 4-up row shrinks more than a
  full-width one, dynamically, without a JS resize observer.
- `font-size: clamp(...)` on the value (`0.85rem`–`2.25rem`) and label
  (`0.7rem`–`0.95rem`), all `!important` (Streamlit's own rules come from a
  single-class emotion selector, so `!important` is necessary and sufficient
  to win regardless of source order).
- `white-space: normal; overflow-wrap: anywhere` as the hard fallback —
  if the clamp floor still doesn't fit, it wraps to a second line. It should
  never truncate, full stop, regardless of how long the value gets.

Verified with the same playwright rig at 700px and 380px, dark theme, with
the actual live post-seed numbers: `all_inner_texts()` on every
`stMetricValue`/`stMetricLabel` checked for `…`/`...` — none found at either
width, including the exact three values from the user's screenshots
(`3608 of 3608`, `At risk · awaiting your decision` — now wraps to two lines
instead of truncating — and `£0.00 – £4,180.53`).

## 8. Patterns of Concern: 30.9s → 0.28s

`api/clusters.py`'s `find_patterns` grouped receipts by `(merchant_key,
currency)` and, per group, built an `n×n` distance matrix with a Python
nested loop calling `distance(block.loc[i], block.loc[j])` — and worse,
`block.loc[i]` was re-evaluated on *every* inner-loop iteration rather than
once per outer iteration, so a group of size `n` did on the order of `n²`
pandas `.loc` row accesses, not `n²/2`. Fine at the dozens-of-claims-per-merchant
scale this ran at before; the 3000-row seed (§5) pushed common merchants —
Starbucks, Brasserie Lipp, Deutsche Bahn — past 100, some past 150 claims
each (checked directly: 82 merchant/currency groups ≥2 claims, sum of `n²`
across them ≈ 253,000).

Replaced the nested loop with vectorised numpy (`np.subtract.outer` /
`np.maximum.outer` for both the amount-tolerance and the date-window terms;
day differences computed via floor-divided nanosecond deltas to match
`pd.Timedelta.days` exactly, not approximated). Removed the now-unused
`distance()` function — nothing else imported it (checked). Matrix is now a
plain `np.ndarray` rather than a nested Python list, which `DBSCAN(...,
metric="precomputed")` accepts natively.

**Measured directly against the live 3608-row sheet: 30.855s → 0.282s**,
identical 66 patterns found before and after. All 19 `test_clusters.py` cases
pass unchanged (no assertions touched `distance()` directly).

---

## 9. Something worth flagging, not yet acted on

The §5 mock-data cohort is deliberately random — no trend, no seasonality,
per the user's own spec ("randomly"). That widened the GBP travel history
from 12 structured months to 36 months including 24 months of pure noise,
and the forecast fit got *noisier*, not more confident: R² dropped to ~0.10
and RMSE to ~50%, with the indicative range now floored at £0. That's the
opposite of "more accurate prediction forecasting", which was the stated
reason for adding the data in the first place. Flagged this to the user at
the end of round 1; they didn't ask for a change. If tighter forecasts
matter more than sheer receipt count, the extra cohort would need some
trend/seasonal structure rather than uniform randomness — an easy follow-up
to `generate_extra_random` if asked for.

## 10. Files touched this session

`api/forecast.py`, `dashboard/forecast_view.py`, `pages/1_Spend_Overview.py`,
`scripts/h1_demo.py`, `scripts/seed_mock_data.py`, `streamlit_app.py`,
`tests/test_forecast.py`, `README.md` (round 1 — commit `936b56a`);
`api/clusters.py`, `pages/4_Policy_Health.py`, `pages/1_Spend_Overview.py`
(again — one import + one call), `dashboard/style.py` (new file, round 2 —
commit `bbcb5fa`). Plus the live Receipts tab: +3000 rows, id 609–3608.

## 11. Notes for next session

- The R²/RMSE% regression from §9 is real and visible on the dashboard right
  now for GBP (and likely USD/EUR too, not individually re-checked) — worth
  asking the user whether it's acceptable before anyone treats the current
  forecast numbers as meaningful.
- `dashboard/style.py`'s CSS is scoped to `st.metric` only. If a similar
  "long value doesn't fit" complaint shows up somewhere else (a
  `st.dataframe` cell, a chart tooltip, a selectbox option), it's a different
  Streamlit component with its own truncation rule — the container-query
  technique generalises, but it isn't automatically covered by this file.
- No new Python dependency was added — `playwright` was installed and then
  uninstalled from `.venv` in the same session, purely for screenshotting;
  `requirements.txt` is unchanged.
