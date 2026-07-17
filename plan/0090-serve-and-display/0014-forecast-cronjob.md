# 0014 - forecast-cronjob

Type: chore
Branch: chore/0014-forecast-cronjob

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add `ops/deploy/jobs/forecast_cronjob.yml` — a k8s `CronJob` in the `ercotstress` namespace that runs `forecast_day` daily after DAM close, using the cluster's existing job idiom (spec §7).
* Schedule with margin past DAM close (10:00 CT) and past D−1's DAM ingest, verified against both DST states; a run that finds inputs missing must fail loudly and leave the previous pointer intact (spec §7, §8).
* Support hand-run / backfill via the same image + command with `--delivery-date YYYY-MM-DD`.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2b-forecast-day.md` §7 (orchestration — deploy as a CronJob using the existing idiom), §8 (failure modes), §10 (schedule margin & DST is an explicit open choice). Depends on **0013** (`compute.mu.forecast_day` module + `--delivery-date`/`--to-db` CLI, fail-loud behavior); do it first.
* Reuse the *shape* of `ops/deploy/jobs/ingest_cronjob.yml`, **not** its payload — same `api-compute` image, `envFrom` the `api-config` configmap + postgres secrets, `concurrencyPolicy: Forbid`, `restartPolicy: Never`. That job *fetches* ERCOT data; this one *consumes* it.
* **Ordering dependency:** must run after the ingest CronJob has D−1's DAM shadow prices and D's forecast vintages. Schedule with margin rather than chaining (spec §7) — a missing input is a fail-loud, not a degraded forecast (the guard lives in 0013; this branch just must not mask it).
* This is ops surface only — no Python change. The leakage/cutoff correctness all lives in 0013; a wrong schedule can only *starve* the job of inputs (→ fail-loud), never make it dishonest.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `ops/deploy/jobs/forecast_cronjob.yml` (new). Model it on `ops/deploy/jobs/ingest_cronjob.yml` for image, `envFrom`, secrets, and metadata conventions.
* **Spec (spec §7 sketch):**
  * `schedule: "0 16 * * *"` — ~11:00 CT, after DAM close (10:00) + ingest of D−1 DAM. **Cron is UTC; 16:00 UTC ≈ 10–11 CT depending on DST** — pad past close, don't sit on it. Confirm against actual ingest completion times and **both DST states** before trusting it (spec §10); leave a comment stating the CT window each DST offset lands in.
  * `command: [python, -m, compute.mu.forecast_day, --delivery-date, tomorrow, --to-db, --run-id, <current model version>]`.
  * `concurrencyPolicy: Forbid`, `restartPolicy: Never`, `backoffLimit: 0` (next day's tick is the retry; also re-runnable by hand), `activeDeadlineSeconds: 1800` (SF refit + fit + propagate; generous vs the ingest job).
* **Fail-loud, keep prior pointer:** rely on 0013's guard — the job exits non-zero on missing inputs and does not flip the pointer. Do not add a fallback/degraded path in the manifest (no retry-into-staleness). `backoffLimit: 0` so a starved run does not thrash.
* **Backfill note:** document (comment or a sibling `*_job.yml.template`, matching `snapshot_job.yml.template` / `compute_shell_pod.yml.template` convention) how to hand-run a single historic day: same image + command with `--delivery-date YYYY-MM-DD`.
* Do NOT touch: `compute/` (all logic is 0012/0013), `ingest_cronjob.yml` (copy its shape, don't edit it), `api/`, the pointer/DB semantics.

## Commits

<!-- Grouped so the manifest is deployable and the schedule is documented at branch end. -->

* **Commit A — `chore(ops): forecast_day CronJob manifest`**
  * `ops/deploy/jobs/forecast_cronjob.yml` — CronJob on the `ingest_cronjob.yml` idiom (image, `envFrom`, secrets, `Forbid`/`Never`, `backoffLimit: 0`, `activeDeadlineSeconds: 1800`), command `-m compute.mu.forecast_day --delivery-date tomorrow --to-db`.
* **Commit B — `chore(ops): schedule/DST rationale + backfill note`**
  * `forecast_cronjob.yml` — `schedule` comment pinning the CT window under both DST offsets and the ingest-ordering margin; documented hand-run/backfill invocation.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `ops/deploy/jobs/forecast_cronjob.yml` applies against the `ercotstress` namespace and matches the existing job idiom (same `api-compute` image, `envFrom` `api-config` + postgres secrets, `concurrencyPolicy: Forbid`, `restartPolicy: Never`, `backoffLimit: 0`, `activeDeadlineSeconds: 1800`).
* [ ] `command` runs `python -m compute.mu.forecast_day --delivery-date tomorrow --to-db --run-id <version>`; a dry hand-run of the same command with an explicit `--delivery-date YYYY-MM-DD` backfills one day.
* [ ] `schedule` fires after DAM close (10:00 CT) and after D−1's DAM ingest, with a comment showing the CT window it lands in under **both** DST offsets (spec §7, §10).
* [ ] On missing inputs the job exits non-zero and the prior `forecast_current[ercot]` pointer is unchanged (no degraded forecast, no retry-into-staleness); `backoffLimit: 0` (spec §8).
* [ ] No change under `compute/` or `api/`; `ingest_cronjob.yml` untouched.
