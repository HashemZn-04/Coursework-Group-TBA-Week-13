# Handoff 8 — the 1-month RMSE/R² formula bug, and a live-sheet trend-signal top-up

One working session (2026-09-11), picking up directly from `handoff_7.md`'s
§5/§10: the user flagged that the 1-month-ahead RMSE (~52%) and R² (~0.04)
were suspiciously low *and* suspiciously similar across USD/GBP/EUR, and
asked why.

**State at the end of this session:** `pytest -q` → **211 passed, 1
skipped** (same as every prior session). One code fix
(`api/forecast.py`), one new script (`scripts/extend_travel_trend.py`), and
1500 new rows written to the live Receipts sheet (500 "travel" receipts per
currency, `receipt_id` 3609–5108) — **not yet committed**; this session
follows the established pattern of the user committing from their own git
client.

---

## 1. Root cause #1 (confirmed bug, fixed): R² divided by month-count, not degrees of freedom

`horizon_at()` in `api/forecast.py` reconstructs an approximate residual
sum-of-squares from the horizon-widened residual std to compute R²:

```python
horizon_r_squared = 1 - (horizon_std ** 2 * len(fittable)) / total_ss
```

But `residual_std` (which `horizon_std` widens) was built by dividing
variance by **degrees of freedom** (`dof = len(fittable) - 2`), not by the
month count. Multiplying back by `len(fittable)` instead of `dof` inflates
the reconstructed SS_res by a factor of `n/dof` — only ~1.06× on the live
sheet's 36 months, but because true R² here is already small, that
inflation compounds and roughly halves the reported number (GBP: true
0.095 → reported 0.042).

Fixed by swapping `len(fittable)` for `dof` (already in scope). Verified
against the live sheet before/after, category "travel", 1-month horizon:

| Currency | R² (buggy) | R² (fixed formula, same data) |
|---|---|---|
| USD | 0.107 | 0.157 |
| GBP | 0.042 | 0.095 |
| EUR | 0.059 | 0.112 |

RMSE%/RMSE were never affected — that computation didn't have this
n-vs-dof mismatch.

## 2. Root cause #2 (data, not a bug): the mock-data generator leaves 2/3 of the fitted window trend-free

Even the corrected R² (0.10–0.16) was still low, and near-identical across
currencies. Traced to `scripts/seed_mock_data.py`: its trend-following
cohort (`generate_currency`, the one with `travel_trend=(base, slope)` per
currency) only iterates `MONTHS` — 12 months, 2025-09 to 2026-08. Its other
cohort (`generate_extra_random`, 1000 receipts/currency) scatters
*unweighted* across all 36 fitted months, 2024-01 to 2026-12, with no trend
at all. So 24 of the 36 months a linear fit sees carry pure noise, and the
trend signal drops to zero right at the `2026-08` boundary — visible
directly in the live residuals (USD actual/predicted: Jul $4521/$2424, Aug
$3682/$2464, then Oct $938/$2546, Nov $808/$2587, Dec $1028/$2627 — a cliff
exactly where the trend cohort's coverage ends). Same shape, independently,
for GBP and EUR — hence the near-identical numbers across currencies:
same generator structure, same gap.

## 3. Fix: `scripts/extend_travel_trend.py`, a bounded live-sheet top-up

Per the user's explicit ask ("improve predictive power as efficiently as
possible... seed more data if needed, max 500 more per currency"), added a
new script (does not modify `seed_mock_data.py`) that appends up to 500
new "travel"-category receipts per currency — the only category the H1
forecast reads — spread across the full 36-month window on a straight
target line (`100 + 68.57 * month_index`, `month_index` 0..35 from
2024-01), split into ~14 receipts/month with ±15% jitter so each month's
*added* total sits close to the line without being perfectly flat.
Existing rows are untouched; this only appends (`ws.append_rows`, same RAW
value-input-option as `seed_mock_data.py`, for the same reason: Sheets'
locale-aware date parser can silently swap day/month under
`USER_ENTERED`).

Simulated locally first (merging generated rows with a live-sheet pull,
re-running `forecast_next_month`, no writes) to pick `BASE_ADD`/`SLOPE_ADD`
before touching the live sheet — landed on values giving a strong but not
absurd forecast (USD's 1-month figure roughly doubles, to just above its
own historical max month, consistent with a real accelerating trend).

Ran for real: wrote 1500 rows (`receipt_id` 3609–5108, 500 each for
USD/GBP/EUR, ~$93/receipt average). Confirmed against a fresh live pull —
simulated and actual post-write numbers matched exactly:

| Currency | RMSE% (before → after) | R² (before → after) |
|---|---|---|
| USD | 52.8% → 31.4% | 0.157 → 0.573 |
| GBP | 51.9% → 26.5% | 0.095 → 0.650 |
| EUR | 50.3% → 28.1% | 0.112 → 0.602 |

`pytest -q` still 211 passed, 1 skipped after the write.

## 4. Notes for next session

- The 1-month forecast figure moved up meaningfully for all three
  currencies (e.g. USD ~$2,668 → ~$5,247) — expected, since the added
  receipts are deliberately trend-reinforcing and the forecast
  extrapolates the fitted line one month past the anchor. Worth a sanity
  screenshot of the dashboard headline number next session.
- `receipt_id` 3609–5108 are the added rows — delete that range from the
  Receipts tab to undo, same as `seed_mock_data.py`'s own undo note.
- The 2- and 3-month horizons (chart-only, purple bars) still widen by
  `√steps_ahead` off the same, now-larger `residual_std`; not
  independently re-verified this session but nothing in `horizon_at()`
  changed beyond the R² divisor.
- `scripts/extend_travel_trend.py` is a one-off top-up, not wired into
  `seed_mock_data.py`'s `--extra-*` flags — if the sheet ever gets fully
  re-seeded from scratch, this script would need re-running afterward (or
  its logic folded into the main seed script) to keep the gap closed.
