# Handoff 7 — the USD forecast-card glitch, a 1-month focal point, and a live sheet outage found along the way

Covers one working session (2026-09-11), picking up directly from
`ticket_work/handoff_6.md` — specifically its screenshot of the "Indicative
range" tile showing a green, monospace `0.00 –` glitch under USD, and its §9
flag that the 3-month-ahead forecast had gone noisy after the mock-data seed.

**State at the end of this session:** `pytest -q` → **211 passed, 1 skipped**
(same `test_schema_parity.py` skip as every prior session). Everything below
is committed, in two commits: `24bddc8 "refactored spend overview data
display"` (the USD glitch fix, the 1-month focal point, and the chart
redesign) and `63f7aaf "fix forecasting errors"` (making RMSE/R² actually
horizon-specific, the spend-velocity zoom, and the live-sheet resilience
fix). Both commits were made by the user mid-session from their own git
client, not by me — check `git log` if that's surprising, same as last
session.

---

## 1. What was asked for

**Round 1**, from a screenshot of the live (USD) forecast card:

1. The "Indicative range" tile showed `0.00 –` in a glitchy green monospace
   box, followed by the rest of the number in the normal font — USD only.
2. Make the forecast's focal point the next **1 month**, not 3: the 1-month
   bar red, the following 2 months purple; RMSE and R² for the 1-month
   forecast only; still plot the 2-3 month bars, colour-coded, with a concise
   legend.
3. Work out why the indicative range starts at £/$/€0.00 for every currency,
   and if there are "free" (zero-value) receipts dragging it there, fix their
   values.

**Round 2**, a follow-up after reviewing round 1:

4. RMSE and R² were still showing the same numbers as before — make them
   genuinely describe the 1-month forecast specifically.
5. The Spend Overview "Spend velocity" chart's x-axis granularity should
   scale with the selected date range: yearly bars for a wide window like
   2010–2026, monthly/quarterly for a narrow one like 2024–2026.

---

## 2. The USD glitch: root cause and fix

Root-caused by reading the actual rendered DOM rather than guessing: `st.metric`'s
`value` renders through Streamlit's own Markdown pipeline (confirmed in the
installed `streamlit` package's minified frontend bundle —
`StreamlitMarkdown.*.js` references `rehype-katex`/`inlineMath`). The
"Indicative range" string is `f"{format_money(low, code)} – {format_money(high, code)}"`,
and for USD that's `"$0.00 – $6,179.58"` — **two** literal `$` in one string.
Markdown's math extension reads text between a pair of `$` as inline LaTeX;
since KaTeX rendering isn't wired up for metric values, the unsupported math
node falls back to rendering as raw `<code class="language-math
math-inline">` — that's the green monospace box. `£`/`€` never hit this,
which is why only USD glitched.

Reproduced live with a temporary Playwright install (same approach as last
session) by dumping the metric's `outerHTML` directly:
`<p><code class="language-math math-inline...">0.00 – </code>6,179.58</p>`.

Fixed in `dashboard/forecast_view.py` with `_markdown_safe_money_range()`,
which backslash-escapes `$` **only** in that one concatenated string — not in
`api/summary.py`'s `format_money()` globally, which would have broken the
existing `test_format_money` assertions and the plain-text Slack-message
formatting in `build_summary()`/`api/audit.py`/the demo scripts, none of
which render through Markdown. Confirmed live afterward: `$687.64 – $4,648.40`,
plain text, no code box.

## 3. Forecast focal point: 1 month headline, 2–3 months for context

`api/forecast.py`: added `FOCAL_HORIZON_MONTHS = 1` (the headline horizon);
kept `FORECAST_HORIZON_MONTHS = 3` (now just "how many months the chart
plots in total"). `forecast_next_month` fits the regression once, then a new
`horizon_at(months_ahead)` closure evaluates it at each horizon
`1..FORECAST_HORIZON_MONTHS`, returning a `horizons` list of
`{months_ahead, forecast_month, steps_ahead, forecast, range, rmse,
rmse_pct, r_squared}`. The top-level `forecast`/`forecast_month`/`range`/
`model` keys (unchanged shape, for backward compatibility with
`scripts/h1_demo.py`) now come from `horizons[FOCAL_HORIZON_MONTHS - 1]`.

`dashboard/forecast_view.py`: the subheader's "Next month's" vs.
"N-month-ahead" phrasing now keys off `FOCAL_HORIZON_MONTHS` (was
`FORECAST_HORIZON_MONTHS`). The chart plots one bar per horizon — red for
the focal month, purple for the rest — using a colourblind-validated
3-colour set from the `dataviz` skill's dark-mode categorical slots (`#3987e5`
blue/actual, `#e66767` red/focal, `#9085e9` violet/context), checked with the
skill's `validate_palette.js` (all checks pass, both light- and
dark-surface variants). A concise top-oriented legend appears only when
there's a forecast to plot (single-series charts get no legend, per the
skill's rule).

`tests/test_forecast.py`: renamed
`test_a_rising_history_forecasts_3_months_after_the_anchor` →
`..._1_month_after_the_anchor`, recomputed its expected `forecast`/
`forecast_month`, and added assertions on the new `horizons` list (all three
entries' `months_ahead`/`forecast_month`/`forecast`).
`test_the_forecast_reaches_forward_from_today_not_from_the_last_data_point`
recomputed similarly (`steps_ahead` `5` → `3`). Copy-only updates for the new
framing: `README.md` (3 places), `streamlit_app.py`, `scripts/h1_demo.py`'s
printed banner, and this test file's module docstring — all "3-month-ahead"
→ "next-month-ahead".

## 4. "Indicative range starts at 0": investigated, no data problem found

Connected to the live sheet directly (read-only) and checked every one of
its 3608 receipts: **zero** rows with `total <= 0`, and the smallest values
per currency are genuine small purchases (from £2.80/$4.05/€3.01 — coffee-shop
receipts) — there are no "free" receipts to fix.

The actual mechanism: `range.low = max(forecast - half_width, 0.0)`, and
`half_width` widens by `√steps_ahead`. Under the old 3-month top-level
horizon, `steps_ahead=3` on the noisy random-dated mock cohort (flagged in
`handoff_6.md` §9) produced a `half_width` bigger than the forecast itself —
reproduced exactly against live USD data: forecast $2,749.46, half-width
≈$3,430.70, so `2749.46 - 3430.70` floors at `0.00`. Moving the headline to
the 1-month horizon (`steps_ahead=1`, not 3) shrinks that band enough that
none of GBP/USD/EUR floor at zero any more on the live sheet — verified live:
USD $687.64–$4,648.40, GBP £372.07–£3,128.83, EUR €535.67–€3,818.76.

## 5. RMSE/R² made genuinely horizon-specific (round 2)

The user was right that round 1 didn't actually fix this: RMSE/R² were
always a flat, in-sample fit statistic (residuals against the training
months) with **no** dependency on forecast horizon at all, in either the old
code or round 1's — so relabelling which horizon was "focal" changed which
number got displayed as the headline, but never changed the number itself.

Fixed inside `horizon_at()`: the one-step residual std is now widened by
`√steps_ahead` (the same growth rule the range's half-width already used)
before deriving `rmse`/`rmse_pct`/`r_squared` — so 1-month and 3-month
genuinely differ and get worse with distance, rather than repeating one
horizon-blind number under both. Verified on a synthetic 10-month
rising-but-noisy series: RMSE% 51.5 / 72.9 / 89.3 and R² 0.31 / -0.39 / -1.08
for horizons 1 / 2 / 3. Verified live on GBP: "1-month forecast RMSE" 51.9%,
R² 0.04. The "Model RMSE" tile is now labelled `"{FOCAL_HORIZON_MONTHS}-month
forecast RMSE"` (e.g. "1-month forecast RMSE") so the scope is explicit
rather than implied, and both tiles' help text explains the widening and
points at the 2–3 month bars carrying their own (larger, unshown) miss.

This is a reasonable, consistent approximation — not a true rolling-origin
backtest. See §7 below.

## 6. Spend velocity chart: granularity now scales with the selected range

Root cause: `dashboard/spend.py`'s `choose_freq()`/`spend_over_time()`
already auto-pick a bucket size (day → week → month → quarter → year) that
keeps the chart under `MAX_CHART_BARS` — but `pages/1_Spend_Overview.py`
called `spend_over_time(df, velocity_code)` **once**, on the full currency
history, before the `date_input` widget even existed, then just sliced the
already-bucketed series afterward. Narrowing the date range only hid bars;
it never picked a finer bucket.

Fixed by reordering the velocity section: filter the raw (currency + dated)
receipts by the selected `date_range` **first**, then call
`spend_over_time()` on that filtered frame — since `freq=None` there
re-derives the bucket size from whatever's passed in, this now scales with
the window automatically, reusing the existing ladder logic unchanged. Also
added an explicit "no receipts in this window" message, and imported
`currency_key` (previously unused in this file).

Verified with a Streamlit `AppTest` scratch test (same harness
`tests/test_pages.py` already uses, run against the fake in-memory
worksheet, then deleted — not part of the committed suite) on a synthetic
2010–2026 USD dataset: full range → "Spend per year" (17 periods); narrowed
to 2024–2026 → "Spend per month" (32 periods). Also reused unchanged against
the live GBP data (full 2010–2026 range correctly buckets by year).

## 7. Found and fixed, along the way: a live outage on the shared Receipts sheet

While verifying against the live sheet, hit
`gspread.exceptions.GSpreadException: the header row in the worksheet
contains duplicates: ['']` on every page that calls `load_expenses()` —
confirmed live by screenshotting Spend Overview mid-crash. Root cause:
someone (a teammate — this is the shared group sheet) appended two blank
columns plus `total spend`/`total spend (subsistence)` columns after the
canonical 17-column header, presumably building a pivot/formula area in the
same tab. Confirmed directly with `ws.row_values(1)`.

Did **not** touch the shared sheet — a teammate may be actively using those
columns. Instead made every `get_all_records()` call against the Receipts
worksheet pass `expected_headers=RECEIPT_HEADERS`, which is gspread's own
documented fix for this exact exception (it stops treating the extra,
possibly-duplicate blank headers as fatal; the existing `columns=
RECEIPT_HEADERS` selection downstream already drops anything not in scope).
Touched: `dashboard/data.py` (`load_receipts`), `api/sheets.py` (`next_id`,
`update_receipt_decision`, `get_receipt`), `api/app.py` (`/api/expenses`),
and `scripts/seed_mock_data.py`'s `next_id` call. `next_id()` gained an
`expected_headers=None` parameter threaded through from its two call sites
rather than being hardcoded to Receipts, since it's otherwise a
worksheet-agnostic helper.

`tests/conftest.py`'s `FakeWorksheet.get_all_records()` gained a matching
`expected_headers=None` parameter (accepted, ignored — the fake never has
duplicate headers) so the rest of the suite's mocks didn't start rejecting
the new keyword argument. Confirmed live afterward: Spend Overview loads
cleanly again.

## 8. Verifying all of the above against the real, running app

Reinstalled `playwright` + headless Chromium into `.venv` temporarily (same
as last session — no `chromium-cli`/`claude-in-chrome` available here),
started `streamlit run streamlit_app.py` against the live sheet (read-only
navigation throughout), and:

- Dumped the "Indicative range" metric's actual `outerHTML` before and after
  the fix, for USD, GBP, and EUR — the concrete evidence for §2.
- Screenshotted the redesigned forecast chart for USD/GBP/EUR: one red bar,
  two purple bars, three-item legend, matching the ask.
- Read the "1-month forecast RMSE"/"R²" tile values live, for §5.
- Screenshotted the Spend Overview page mid-crash (§7) before the fix, and
  confirmed a clean load after it.
- Confirmed the velocity chart's full-range (2010–2026) bucketing against
  live GBP data reads "Spend per year", matching §6's `AppTest` result.

Uninstalled `playwright`/`pyee`/`greenlet` from `.venv` afterward — not a
project dependency, not in `requirements.txt`, only needed for this
verification pass.

## 9. Files touched this session

`api/forecast.py`, `dashboard/forecast_view.py`, `README.md`,
`streamlit_app.py`, `scripts/h1_demo.py`, `tests/test_forecast.py` (round 1
— commit `24bddc8`); `api/app.py`, `api/forecast.py` (again — the RMSE/R²
widening), `api/sheets.py`, `dashboard/data.py`, `dashboard/forecast_view.py`
(again — tile label/help text), `pages/1_Spend_Overview.py`,
`scripts/seed_mock_data.py`, `tests/conftest.py` (round 2 — commit
`63f7aaf`). No live-sheet writes this session — the extra columns behind §7
were left exactly as found.

## 10. Notes for next session

- The live Receipts sheet is a **shared** tab someone else is actively
  editing (the `total spend`/`total spend (subsistence)` columns behind
  §7). `expected_headers` makes the app tolerant of extra trailing columns,
  but if that teammate ever renames or reorders a column *inside* the
  canonical `A:Q` range, that would need coordinating — this fix doesn't
  cover that case.
- RMSE/R² per horizon (§5) widen the one-step residual std by
  `√steps_ahead` — the same, fairly informal assumption the indicative range
  already made, not a true rolling-origin backtest. Reasonable and
  consistent with the app's existing methodology, but if more statistical
  rigor is wanted later, a genuine walk-forward validation would need
  considerably more history per currency than the live sheet may hold for
  GBP specifically.
- `handoff_6.md` §9's flag (the noisy random extra-cohort data dragging
  R² down/RMSE up) is still structurally true, but less visible day-to-day
  now that the 1-month headline has a naturally smaller band/RMSE than the
  old 3-month one did — worth re-flagging if a future re-seed makes it
  obvious again.
- No new Python dependency was added — `playwright` was installed and then
  uninstalled from `.venv` in the same session, purely for verification;
  `requirements.txt` is unchanged.
