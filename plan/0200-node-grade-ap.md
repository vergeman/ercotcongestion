# 0200 - node-grade-ap

Type: feat
Branch: feat/0200-node-grade-ap

## Goal

* Make Brief node Detection use average precision against the settled top 10% of absolute-congestion nodes.
* Make Brief node Timing use the same settled top-10% label within each delivery hour.
* Re-materialize historical Brief grades before exposing the new metric and copy.

## Context

* Constraint Detection and Timing are already AP-based; the node cards currently headline equal-size top-10% set overlap (`capture@10%`).
* Node values must remain absolute `SPP − system λ`; the change alters ranking labels, not the sign-agnostic nodal profile or Magnitude calculation.
* A production sample showed the proposed daily node AP is well-behaved, but historical persisted capture values cannot be mixed with new AP values in the Brief history.

## Approach

* Work in: `compute/analysis/grade.py`, `compute/analysis/brief_grade.py`, `compute/analysis/tests/test_grade.py`, `api/schemas/analysis.py`, `api/services/analysis/panels.py`, `web/src/pages/BriefPage.tsx`, `docs/METRICS.md`, and `compute/analysis/README.md`.
* In `grade.py`, add a tie-stable settled top-fraction label builder. It must select `ceil(0.10 × N)` nodes from the full, aligned scored node set, using settled absolute congestion and the existing stable ordering rule.
* Refactor `_metrics()` / `grade_profiles()` to accept separate daily and hourly event labels. Preserve the present constraint labels: daily is any settled shadow-price row; hourly is a settled shadow-price row.
* For nodes, derive the daily label from each node's settled daily total. Compute `detection_ap` by ranking all nodes with daily forecast absolute congestion against that label.
* For node Timing, derive a settled top-10% label independently in every delivery hour. Compute AP and chance-adjusted skill per hour, then average the hourly skills. This preserves the current per-hour Timing meaning while replacing capture with AP.
* Set node `timing_daily_skill` from the same daily node AP and its selected-label rate. Use `detection_ap`, `timing_daily_skill`, and `timing_hourly_skill` as the node headline contract, just as for constraints.
* Retain `top_decile_daily_capture` and `top_decile_hourly_capture` only as optional diagnostics during the migration; remove their client reads. Do not silently reuse a stored capture value as AP.
* Update `GradeSupport` for node grades so the displayed daily/hourly rates describe the selected top-10% labels, not the old epsilon event diagnostic. Preserve the epsilon labels only if a diagnostic caller still needs them.
* Update `BriefPage.tsx` in the same change: bind node Detection to `detection_ap`, node Timing to `timing_daily_skill` and `timing_hourly_skill`, and use the same AP / chance-adjusted formula family as constraints. State that nodes are selected by settled top-10% absolute congestion and that hourly labels are selected separately each hour.
* Update `METRICS.md` and `compute/analysis/README.md` only with the implemented AP definition. Replace node capture examples with AP examples and retain the absolute-congestion caveat.
* Add unit coverage for: daily node top-10% labels; hourly per-hour labels; stable ties at the cutoff; AP differing from capture for an item just outside forecast top 10%; chance-adjusted daily and hourly node scores; and no regression to constraint grades.
* Add API/UI tests proving node cards read the AP/skill fields and no longer select `top_decile_*_capture`.
* Do NOT touch: Scoreboard metrics, SF-map diagnostics, forecast artifacts, or the signed nodal profile used outside Brief grades.

## Data migration

* No SQL schema migration is required: `analysis_grade_daily.model`, `.persistence`, and `.detail` already store JSON grade payloads.
* Add a one-off, resumable backfill invocation or documented runbook using `compute.jobs.materialize_brief_grade` for every settled day, run ID, and horizon served by Brief history. It must overwrite every node row before the web deployment reads the new fields.
* Validate completeness with a read-only query that checks all expected `(run_id, delivery_date, horizon, subject = 'nodes')` rows have a common recalculation timestamp and non-null `detection_ap`, `timing_daily_skill`, and `timing_hourly_skill` for model and persistence.
* Deploy order: calculation/API support → full backfill → web/docs copy. If a backfill cannot complete first, gate the new web reads behind a metric-version flag; do not blend capture history with AP history.

## Acceptance

* [ ] Node Detection is AP over all scored nodes, with the settled daily top 10% of absolute congestion as positive labels.
* [ ] Node Timing is chance-adjusted AP using independently selected settled top-10% labels in each hour, averaged across hours; the daily value is the daily Detection skill counterpart.
* [ ] Constraint metrics and all Magnitude calculations are unchanged.
* [ ] BriefPage, METRICS, and the analysis README describe only the fields actually served after the backfill.
* [ ] Historical node grade rows are fully re-materialized before the AP UI is enabled; no Brief history combines capture and AP values.
* [ ] Grade, API, and web tests cover the new node AP path and pass.
