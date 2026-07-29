# 0124 - filter-engine

Type: feat
Branch: feat/0124-filter-engine

## Goal

* Build a deterministic filter/recommendation engine (`compute/analysis/brief.py`) that ranks the day's constraints, nodes, and separations from the full SF+μ̂ artifact.
* Emit one JSON brief per `(run_id, delivery_date)` — per-hour drill-down + day roll-up — persisted append-only like the SF artifact.
* Compute the brief in a job after `daily_forecast` publishes; serve read-only via `GET /analysis/brief`; re-run after-action (F6) when DAM data lands.

## Context

* `last_mile.md` / `last_mile_fable.md` did this analysis by hand for June 30; this generalizes it to code — no new modeling, no LLM, every number reproducible.
* Reads `forecast_sf_artifact` (S matrix + μ̂) and `forecast_nodal` (P10/P50/P90) directly; F6 adds DAM shadow prices + SPPs (~13:30 CT on D−1).
* `api/matrix.py:_sp_metadata` drops hubs/LZs (no geocode) — the engine must read the artifact directly and NOT inherit that filter; F5a depends on it.
* Sign convention (`docs/SF.md`): SF < 0 = import; cell contribution = −SF·μ.

## Approach

### Commit 1 — primitives + golden tests

* Work in: `compute/analysis/brief.py` (new module, `compute/analysis/__init__.py`), tests in `compute/analysis/tests/`.
* Implement three pure formulas: `cell k[c,sp] = −SF·μ`; `cong[sp] = (−Sᵀμ)`; `pair[c;a→b] = μ·(SF[c,a] − SF[c,b])`.
* Global params: `SF_MEANINGFUL = 0.05`, `TOP_K_CONSTRAINTS = 10`, `TOP_N_NODES = 5`.
* Gate on June 30 golden numbers before anything wraps them: OLNEY−LGW $159.19 (drivers 6830 $74.36 / $42.07); JUNCTION−CFLATS $69.10 (TREADW $43.00).
* Do NOT add narrative, persistence, or DB access in this commit.

### Commit 2 — F1/F2/F3 (pure re-ranking)

* F1: per-hour `hour_score[c] = |μ̂[c]| × Σ|SF[c,sp]|` reported alongside daily score `Σ_hours |μ̂|×Σ|SF|`; output top-K with both ranks (never conflate hour vs daily).
* F2: global top-N import (SF<0) / export (SF>0) SPs by |k| from the full artifact — never the visible frame. Per node: SF, $/MWh, SP type, geocode.
* F3: per-constraint stats — side balance (count + Σ|SF| per sign), reach (SPs with |SF|≥threshold), concentration (top-5 share, peak |SF|, p95), max pair contrast. Labels are derived at read time, never stored.
* Each family is a pure `(S, μ, metadata) → ranked list of dicts`.

### Commit 3 — artifact reader + F5a hub dipole

* Add an artifact accessor that reads S + μ̂ from `forecast_sf_artifact` **including hubs/LZs** (bypass `_sp_metadata`); consider fixing `_sp_metadata` in the same pass.
* F5a: project `cong[·]` onto the canonical ~12 hubs/LZs; report min, max, spread, and top pair-contribution drivers. Always emitted, no endpoint guardrails.

### Commit 4 — F4 hotspots + common nodes

* Hotspots: top SPs by |cong[sp]| (forecast P50 basis), each decomposed into top per-constraint contributions; flag reinforcement vs cancellation (`Σ|k|` vs `|Σk|`).
* Common nodes: SPs in the F2 top-N of ≥2 F1 constraints — the confluence anchors.

### Commit 5 — brief assembly + job + persistence + route

* Assemble `brief[hour]` (constraints+F2+F3, hotspots, hub_dipole, provenance) and `brief.day` (daily ranks, peak hours, watchlist across ≥m hours) per Output shape.
* Job: `compute/jobs/daily_brief.py`, run after `daily_forecast` publishes; persist append-only keyed to run (mirror the SF artifact pattern).
* Serve: `api/analysis.py` → `GET /analysis/brief?delivery_date=…`, read-only; register router in `api/main.py`. Wire the disabled Analysis nav item as the home.

### Commit 6 — F6 after-action

* Re-run F1/F4/F5 with realized DAM μ through the **same** S; diff against forecast.
* Emit ranking scorecard (recall-in-top-K, exact hits, biggest severity miss / false alarm), per-story decomposition (forecast spread → μ̂→μ_DAM Δ → spatial residual → DAM SPP spread), per-hub forecast/reconstruction/realized triple + P10–P90 band check.
* Re-run in the grading tick when DAM lands (idempotent, same pattern as `grade_day`).

### Commit 7 — F5b best pair (last, highest risk)

* Max |cong[b]−cong[a]| over quality-gated pairs, with driver waterfall + dominance share.
* Guardrails in order: cluster geographic duplicates (keep one representative); require allowed SP-type; require DAM-SPP coverage for both endpoints; suppress pairs already told by F5a. Rank by absolute forecast spread.
* NOTE (as built): the geocoded `sp_type` vocab is `{OTHER, RN, PCCRN, PUN, hub, load_zone}` — the walkthrough's own headline nodes (OLNEY/LGW/CFLATS) are typed `OTHER`, so a literal `{hub,LZ,RN,gen,storage}` allowlist drops them (min flips to DORA_SLR_RN). Default gate therefore requires only a *non-null* type; `allowed_types` is a param to tighten later. This preserves the documented result and matches `last_mile.md`'s warning against over-restrictive allowlists.

* Do NOT touch: modeling / fit code; do NOT add LLM commentary, manual source–sink builder, alerts, change-since-yesterday, or historical analogs (all deferred per `last_mile.md`).

## Acceptance

All verified against the served `mu-all-v1` June-30 artifact in the dev stack;
33 hermetic tests in `compute/analysis/tests/` pin every golden number.

* [x] `compute/analysis/brief.py` primitives reproduce the June 30 golden numbers (OLNEY−LGW $159.19; JUNCTION−CFLATS $69.10). — `test_brief.py`
* [x] F2/F4 rank over the full artifact including hubs/LZs; F5a reads the 13 canonical hubs (`*AVG` excluded) by name despite absent geocode metadata. — `test_families.py`, `test_hub_dipole.py`, `test_nodal.py`
* [x] F1 reports `hour_rank` and `daily_rank` as distinct fields (107__B: hour 1 / daily 2). — `test_families.py`
* [x] F5b best pair = OLNEY↔LGW $159.19 after dedup + guardrails; F5a suppressed, DAM coverage gated. — `test_best_pair.py`
* [x] `compute/jobs/daily_brief.py` upserts one brief per `(run_id, delivery_date, horizon)` with per-hour entries + `day` roll-up matching the Output shape. Re-run is byte-identical (idempotent). — verified in stack
* [x] `GET /analysis/brief?delivery_date=…` returns the persisted brief read-only; `available:false` (not 404) when absent. — `api/analysis.py`, registered in `main.py`
* [x] F6 fills `after_action` per hour + day roll-up when DAM μ + SPPs exist (recall@10 0.7, top-2 exact; OLNEY−LGW 159.19→250.08→237.40), null before; provenance `dam_match_coverage` populated. — `test_after_action.py`
* [x] Brief provenance records run_id, delivery_date, horizon, artifact_date, mu_basis, dam_match_coverage. — `assemble.py`

### As-built deltas from the plan

* **Module split:** primitives in `brief.py`; families in `families.py`; F6 in
  `after_action.py`; assembly in `assemble.py`; metadata provider in
  `metadata.py`. (Plan implied a single `brief.py`.)
* **Persistence:** table `analysis_brief` (migration `38_analysis_brief.sql`),
  JSONB, keyed `(run_id, delivery_date, horizon)` with `ON CONFLICT` upsert — an
  in-place read-cache, not the append-only blob the plan sketched. Migration was
  applied to the dev DB during Commit 5; **apply it wherever else this runs.**
* **Extra payload:** each hour also carries `common_nodes` (F4 confluence
  anchors), and F6 adds `best_pair_decomposition` alongside the hub-dipole one.
* **F5b type gate** relaxed to "any typed SP" — see the F5b NOTE above.
* **Scheduling (0126):** the "Not wired" gap is closed in `0126-include-daily-brief-jobs.md`
  — `daily_forecast.py` now chains the brief in-process each `--to-db` tick, and
  `compute/jobs/backfill_briefs.py` backfills a range from existing artifacts.
