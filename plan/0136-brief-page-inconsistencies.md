# 0136 - brief-page-inconsistencies

Type: fix
Branch: fix/0136-brief-page-inconsistencies

## Goal

* Make `/analysis/grade` return settlement-pending for unsettled days instead of a fake zero grade.
* Use one median convention for "median Σμ" everywhere on the Brief.
* Fix the Top Constraints asterisk threshold to match the table's actual k, and make
  the server the single source of truth for that row cap.
* Name the standout min-history threshold so it stops reading like the row cap.

## Context

* Found during a 2026-08-14 audit of the v6 Brief against independent SQL for dev days
  2026-08-12 (settled) and 2026-08-13 (forecast-only). **All core math verified exact** —
  grade metrics, top-constraints, top-nodes, context, hero. These three are the only
  remaining discrepancies; none is a calculation bug, all are convention/edge issues.
  (A fourth — negative history bars rendering flat — was fixed separately in the
  diverging `HistoryBars` rewrite and dropped from this plan.)
* The BriefPage's unsettled grade renders correctly today only because of a client-side
  hero-basis guard (item 1) — the defect is latent, not visible.

## Approach

Work in: `api/analysis.py`, `api/models.py`, `web/src/pages/BriefPage.tsx`,
`web/src/api/client.ts`, `web/src/api/types.ts`

**1. Unsettled-day grade looks real** — `get_grade` (`api/analysis.py:643`)

* For 2026-08-13 (no DAM yet) the endpoint returns `graded: true` with
  `magnitude_overlap: 0.0` and null APs — a real-looking zero score. Example:
  `GET /analysis/grade?delivery_date=2026-08-13` → `constraints.model.magnitude_overlap: 0.0`.
* Only BriefPage's hero-basis check (`hero.provenance.basis === "settled"`,
  `BriefPage.tsx:574-588`) hides it. Any other consumer — or the grade
  materialization job run before DAM lands — would persist/show a false zero.
* Fix server-side: when `_settled_mu_profile` is empty, return the ungraded/pending
  shape (`graded: false, unavailable_reason: "settlement_pending"`), never metrics.
  Keep the client guard.

**2. Two "median Σμ" conventions on one page**

* Context chronic median includes zero days (`api/analysis.py:909` — full 30-length
  history); Top Constraints whisker median is nonzero-days-only (`api/analysis.py:809`).
* Example, BRUNI_69_1|DFOAVLO5 on 2026-08-12 (bound 27 of 30): Context shows
  median **$1,300.62**, the Top Constraints whisker tooltip shows **$1,358.63**.
* Pick one convention (suggest nonzero-only, since the chronic panel already prints
  "27 / 30" beside it) and label it; apply to both.

**3. Asterisk threshold hardcoded to 15** — `BriefPage.tsx:501` (constraints; nodes at `:647`)

* `row.forecast_rank > 15` marks "not a forecast leader", but the constraints table
  requests k=10 (`client.ts:307` `fetchTopConstraints`). DAM leaders with forecast
  rank 11–15 escape the mark.
* Example, 2026-08-12: `1715__B|DSALHUT5` (DAM rank 2, forecast rank 11) and
  `TREADW_YELWJC1_1` (DAM 10, forecast 12) show no asterisk. Nodes (k=15) are consistent.
* Fix by making the server own the row cap end-to-end: return the served `k` in
  both `TopConstraintsAvailableResponse` and `TopNodesAvailableResponse`; stop the
  client sending `k` (`fetchTopConstraints`/`fetchTopNodes`); default both endpoints
  to `k=10` with ceiling `le=15` (was `le=100`); read the served `k` for the asterisk
  with no client-side fallback (mark nothing when `k` is somehow absent). This also
  unifies the two tables at 10 — the post-settlement union still floats to ~10–20 rows.

**4. Standout min-history threshold is a bare `10`** — `analysis.py`

* Four standout gates hardcode `10` for "minimum trailing history days to trust a
  baseline" (`_standout_rows`, `_node_standout_rows`, `_settled_standout_keys`,
  `_settled_node_standout_keys`). It collides numerically with `k`'s default and
  reads like the row cap, but is unrelated — it gates eligibility, not row count.
* Extract `MIN_STANDOUT_HISTORY_DAYS = 10` beside the other module constants and use
  it in all four; leave the unrelated `10`s (`top_fraction=0.10`, the p10 quantiles).

Do NOT touch: the grade math in `compute/analysis/grade.py` (verified correct), the
ESSP grouping fallback in `get_top_nodes` (duplicate BAFFIN/STELLA/TGW rows are a
source-data limitation, by design), or the hero's artifact-vocabulary restriction
(deliberate; the gap is the "Outside forecast" fact).

## Acceptance

* [x] `GET /analysis/grade?delivery_date=<unsettled day>` contains no numeric metric;
      both halves report settlement-pending. Settled days unchanged
      (2026-08-12 values still match `analysis_grade_daily`).
* [x] One median convention: the same constraint shows the same median Σμ in Context
      and in the Top Constraints whisker tooltip.
* [x] Post-settle Top Constraints: every row absent from the forecast top-k carries
      the asterisk; rank 11–15 rows no longer slip through at k=10.
* [x] Server owns the row cap: both endpoints return `k`, the client no longer sends
      it, both default to 10 with ceiling `le=15` (`k=16`→422), and the asterisk
      threshold reads the served `k` with no client-side constant.
* [x] `MIN_STANDOUT_HISTORY_DAYS` replaces all four bare `10` history gates; the
      `/analysis/standouts` output is unchanged.
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.
