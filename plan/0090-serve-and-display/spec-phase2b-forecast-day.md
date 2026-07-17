# Spec — the `forecast_day` production job

**Context:** `serving-and-display-design.md` (Phase 3) and
`spec-phase2a-nodal-panel.md` (the panel + SF+μ artifact this job emits). This is
the daily job that turns "a validated backtest model" into "a live forecast for
tomorrow." It is new operational surface: the model was only ever run walk-forward over
*history*; nothing yet runs it *forward*.

**One line:** at/after DAM close on D−1, produce the forecast for delivery day D — nodal
P10/P50/P90 + point, plus the per-day SF+μ artifact — write to Postgres, flip the
pointer.

---

## 1. Why this is a fit-then-predict job (the key constraint)

**The μ-model persists predictions, never fitted models.** `mu_model.py` has no
`joblib.dump`/booster save — `walk_forward` refits both heads on each trailing window and
emits preds; `save_preds`/`load_preds` round-trip only the *outputs*. So there is no
weight file to load and serve (this is also why §0 of the panel spec rejects
"serve the GBM boosters"). `forecast_day` therefore **fits the heads at run time** on the
trailing window and predicts D.

That is cheap and, crucially, **legal by construction**: `features.py` reads every
covariate at the DAM-close vintage (`dam_close`, `history_cutoff`, `_dam_close_expr`), and
`binding_history` is keyed per `(delivery_day, constraint)` at DAM close. The feature
panel for *tomorrow* is fully buildable *today* — nothing about forward inference is
blocked; it is what the feature layer was designed for.

---

## 2. Contract

**Inputs** (all knowable at DAM close 10:00 CT, D−1):
- Zonal load forecast, regional wind/solar forecasts for D — newest vintage ≤ DAM close
  (`features.load_forecast_panel` / `wind_forecast_panel` / `solar_forecast_panel`).
- Zonal outage MW at DAM-close vintage (`features.outage_panel`).
- DAM shadow prices + congestion through `history_cutoff(D)` (= end of D−1; D−1's DAM
  cleared on D−2 and is published before close for D) — for the trailing SF fit, the
  binding-history features, and lagged-μ.
- Calendar features for D.

**Outputs** (for delivery day D):
- `forecast_nodal` rows: `(run_id, D, ts, sp, p10, p50, p90, point)` for 24 h × ~1k SP.
- `forecast_sf_artifact`: the day's SF matrix + `E_mu` vector (panel spec §4a).
- `forecast_current[ercot]` pointer upserted to `run_id`.
- A run log line per stage + a coverage/novelty summary (§7).

**Never** written: realized `Y` (absent until D+1) or driver rows (reconstructed on read).

---

## 3. Two stages

```
forecast_day(D):
  # stage 1 — μ inference (fit heads on trailing window, predict D)
  panel = build_feature_panel(conn, D-TRAIN_DAYS ... D, arms=("lag","geo","wx"))
  wp    = predict_day(panel, D)          # (24h × candidate keys): p_bind, mu_gbm

  # stage 2 — propagate through the honest SF map (panel spec §3)
  M, C  = load_shadow_prices(conn, D-WINDOW_DAYS, D), load_congestion_panel(...)
  eps   = residual_pool(all_validated_backtest_weeks)      # fixed pool, panel spec §7
  _, panel_out = propagate_window(s=D, end=D+1d, M=M, C=C, wp=wp, eps=eps,
                                  want_panel=True)          # no want_metrics: Y absent
  sf_mu = build_sf_mu_artifact(SF, E_mu)                    # panel spec §4a

  # persist + publish (§6)
  write_nodal(conn, run_id, D, panel_out); write_sf_artifact(conn, run_id, D, sf_mu)
  upsert_pointer(conn, "ercot", run_id)   # this feature's own forecast_current
```

### 3.1 Stage 1 — `predict_day` (the one new modeling wrapper)
`walk_forward` already does "fit heads on a trailing window, predict the next block" —
`predict_day` is **one iteration of that loop with the prediction block = D's 24 h**,
reusing `fit_bind_head`, `fit_mu_head`, `fit_mu_climatology`, `target_encoding`,
`apply_encoding`, `feature_cols`. Prefer extracting the loop body `walk_forward` already
contains over duplicating it, so the fit path can't drift from the validated one.

- **Candidate constraint universe = keys present in the trailing window's binding
  history.** A constraint with no history has no features and gets no prediction — this
  is the coverage gap (handoff §5.3), reported, not silently zero. Emit a novelty count
  (§7): "N keys enforced in yesterday's data that the model has never fit."
- **Arms = the shipped `all`** (`("lag","geo","wx")`), matching the validated config.
- Output `wp`: `(interval_ts, key, p_bind, mu_gbm)` — exactly the shape
  `propagate_window` consumes (it currently reads `by_week[s]`; the refactor takes `wp`
  directly).

### 3.2 Stage 2 — propagation
Reuses `propagate_window` (panel spec §3) unchanged except `end = D + 1 day` (24 h, not a
7-day score block) and `Y` omitted (no realized outcome yet → the metrics row is `None`;
only the panel is produced). SF is fit on `[D−WINDOW_DAYS, D)` inside `propagate_window`,
which by cutoff discipline includes through end of D−1 and nothing later.

---

## 4. `run_id` semantics

`run_id` names the **model version**, not the day — e.g. `mu-all-v1`. Each daily run
appends a new `delivery_date` under the same `run_id`; the `forecast_current` pointer only
moves when the model *config* changes (new arms, retune, RTC+B re-fit). This keeps the
whole forward track under one queryable id for the scoreboard and lets the API serve "the
current model's forecast for date D" with a single pointer read. Bump `run_id` on any
change that would make two days' forecasts non-comparable.

---

## 5. Cutoff discipline — the load-bearing risk

⚠ This job reads **live inputs**, so it does not inherit the backtest's built-in honesty
(the backtest replays `mu_preds.npz`, already built walk-forward). Every input must be
pinned at **DAM close (10:00 CT, D−1)**:

- The SF fit window ends at `history_cutoff(D)` and **never** includes any interval ≥ D.
- Every covariate read uses the DAM-close vintage expression; do not hand-roll a query
  that grabs the latest row regardless of `posted_datetime`.
- **A two-sided leakage test is a merge blocker.** Build the equivalent of
  `audit_leakage` for the *production* path: assert that forcing any input's vintage past
  DAM close changes the output, and that the honest path uses no interval ≥ D. The
  existing `audit_leakage` will not catch a regression here — it is built around the DAM
  vintage logic, and this job has its own read path (handoff §3, §10).

The handoff calls this "the single easiest way to fabricate skill." Treat the leakage
test as part of the definition of done, not a follow-up.

---

## 6. Persist + publish (self-owned pointer, no legacy coupling)

- `write_nodal` — `psycopg` `COPY` into `forecast_nodal` (panel spec §6). Idempotent per
  `(run_id, D)`: delete-then-copy or `COPY` to temp + upsert, so a re-run of D replaces
  cleanly.
- `write_sf_artifact` — npz under the run dir and/or `forecast_sf_artifact` bytea.
- `upsert_pointer` — `INSERT ... ON CONFLICT (layer) DO UPDATE` on `forecast_current`.
  **This job owns this table**; it does not use `compute/promote.py` (legacy) or the
  symlink tree. Pointer flip is the last step, after rows land, so a reader never sees a
  half-written day.

---

## 7. Orchestration (k8s CronJob)

Deploy as a `CronJob` in the `ercotstress` namespace, using the **cluster's existing job
idiom** (same `api-compute` image, `envFrom` the `api-config` configmap + postgres
secrets, `concurrencyPolicy: Forbid`, `restartPolicy: Never`) — the *shape* of
`ops/deploy/jobs/ingest_cronjob.yml`, not its payload (that job fetches ERCOT data; this
one consumes it).

```yaml
# ops/deploy/jobs/forecast_cronjob.yml  (sketch)
schedule: "0 16 * * *"        # ~11:00 CT, after DAM close (10:00) + ingest of D-1 DAM.
                              # Cron is UTC; 16:00 UTC ≈ 10–11 CT depending on DST —
                              # pad past close, don't sit on it. Verify DST both ways.
concurrencyPolicy: Forbid
command: [python, -m, compute.mu.forecast_day, --delivery-date, tomorrow, --to-db]
activeDeadlineSeconds: 1800   # SF refit + fit + propagate; generous vs the ingest job.
backoffLimit: 0               # next day's tick is the retry; also re-runnable by hand.
```

- **Ordering dependency:** must run after the ingest CronJob has D−1's DAM shadow prices
  and D's forecast vintages. Schedule with margin rather than chaining; if a run finds
  inputs missing, it should **fail loudly and leave the previous pointer intact**, not
  emit a degraded forecast.
- **Backfill:** `--delivery-date YYYY-MM-DD` runs any single historic day through the
  identical path (for gap-fill or the Phase-4 slider), writing under the same `run_id`.

---

## 8. Failure modes & how the job responds

| Condition | Response |
|---|---|
| Missing covariate vintage (ingest late) | Fail; keep prior pointer. No degraded forecast. |
| `implied_shift_factors` returns empty (thin window) | Fail loudly — the map is the product; a mapless forecast is not one. |
| Novel constraints in D−1 data (no model history) | Predict what's coverable; emit novelty count; widen bands / flag (handoff §5.3). Not an error. |
| Re-run of an already-forecast D | Idempotent replace (§6); pointer unchanged if `run_id` unchanged. |
| μ-head fit degenerate (all-zero) | The scorer already declines flat rows; the job should assert non-flat before publishing. |

---

## 9. Verification

- **Backtest reconciliation (the decisive test):** run `forecast_day(D)` for a historic D
  that is *inside* the validated backtest, with inputs restricted to the DAM-close
  vintage, and confirm the nodal panel matches the backtest's panel for D to tolerance.
  If forward inference and walk-forward disagree on a day both can see, one path has a
  bug — almost always a cutoff or feature-construction mismatch.
- **Leakage (§5):** the two-sided test passes; the honest path touches no interval ≥ D.
- **Idempotency:** running D twice yields identical rows and one pointer.
- **Pointer atomicity:** a reader mid-run sees either the old day or the new, never a
  partial panel.
- **Coverage sanity:** report SF-coverage and novelty for D; a sudden coverage drop is an
  ingest problem surfacing, not a silent skill loss.

## 10. Open choices for the implementer

- **`predict_day` via extracted `walk_forward` body vs a thin re-fit** — prefer the
  extraction so the production fit and the validated fit are literally the same code.
- **Schedule margin & DST** — 16:00 UTC is a safe first guess; confirm against actual
  ingest completion times and both DST states before trusting it.
- **Multi-day / intraday** — v1 is one delivery day, once daily. Re-forecasting D as later
  vintages arrive is deferred (would need its own cutoff story).
- **`run_id` bump policy** — write down what constitutes a non-comparable config change so
  the scoreboard's track record doesn't silently splice two models.
