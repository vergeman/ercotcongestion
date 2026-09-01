# 0190 - source-presentation-and-metrics-catalog

Type: refactor
Branch: refactor/0190-comparison-presentation-and-metrics-catalog

## Goal

* Render source-specific labels and coherent chart series from the provenance contract introduced in 0189.
* Consolidate all metric and source documentation into `docs/METRICS.md`.
* Retire the temporary API compatibility fields after the frontend has moved.

## Context

* This plan follows 0189, whose API supplies canonical `SourceDescriptor` values and `series_id` values.
* Weekly backtests and served grades represent one logical visual series but have distinct constructions and IDs.
* Metric documentation currently exists in both `docs/Scoring.md` and `compute/experiments/METRICS.md`.

## Approach

* Work in: Scoreboard and Brief frontend components/tests, `web/src/api/types.ts`, API compatibility schemas/services, `docs/Scoring.md`, `compute/experiments/METRICS.md`, `docs/METRICS.md`, Compute runbooks, and documentation links.
* Drive Scoreboard presentation from API `SourceDescriptor` values and `series_id`, not hard-coded short source strings. Join weekly and daily history by `series_id`, retaining daily-over-weekly precedence on overlap.
* Use precise Scoreboard labels: **Model Forecast**, **Prior-day (Persistence)**, **Trailing-window Average (Baseline)**, **Settled-μ Ceiling (Oracle)**, and **Flat nodal control**. Tooltips disclose whether the value is a backtest or served construction; track-record graph labels may use their compact source-family names.
* Render Brief profiles using their API `SourceDescriptor` labels; never append duplicate explanatory labels or show bare Model, Persistence, Climatology, or Oracle where domain context is absent. Shared source-family labels describe the same role, not necessarily identical values across Brief and Scoreboard constructions.
* After the frontend uses `SourceDescriptor` values, remove the bounded legacy API fields introduced by 0189 and test their absence.
* Start documentation consolidation with `git mv docs/Scoring.md docs/METRICS.md`. Fold in the durable, non-duplicated content from `compute/experiments/METRICS.md`, then delete that source file with no redirect.
* Make `docs/METRICS.md` the sole normative catalog for metric families, canonical IDs, display labels, information cutoffs, construction summaries, series IDs, and deployable/baseline/ceiling/control status. Include legacy IDs only in a migration appendix.
* Repoint every tracked documentation link and operational instruction to `docs/METRICS.md`. Keep executable definition tables concise and avoid duplicate prose catalogs in code.

## Commit groups

1. `refactor(web): render source provenance` — source-descriptor-driven joins, labels, tooltips, and frontend tests.
2. `refactor(api): retire legacy source fields` — remove the 0189 compatibility adapter and cover the final contract.
3. `docs(metrics): consolidate source catalog` — move Scoring, merge/delete experiment metrics docs, and repoint references.

## Acceptance

* [ ] Scoreboard history joins by `series_id`; labels and tooltips disclose each source’s construction.
* [ ] Brief and Scoreboard never render an unqualified source label without domain context.
* [ ] Legacy source fields are absent from final API contracts.
* [ ] `docs/METRICS.md` is the sole authoritative catalog; `docs/Scoring.md` and `compute/experiments/METRICS.md` no longer exist.
* [ ] Frontend, API contract, and documentation-link checks pass.
