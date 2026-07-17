# Spec — persist the nodal forecast panel from `propagate.py`

**Context:** `serving-and-display-design.md` §4.1. This is the one compute item on
the critical path: the forecast map (Phase 2) cannot be served until the per-SP
P10/P50/P90 panel exists as an artifact. Everything else needed is already on disk.

**Scope:** emit the nodal panel (and its deterministic point forecast + drivers) that
`propagate.py` already computes and discards. No modeling change; no change to the
existing weekly-metrics CSV or the R5 verdict. Additive, behind flags.

---

## 0. Architecture: precompute vs reconstruct

The governing rule for *what to store vs. what to compute on read*:

> **Precompute anything with no per-request parameter. Serve-and-reconstruct only where
> the request carries a parameter the precompute can't enumerate.**

- **The nodal panel (P10/P50/P90/point) is a daily artifact with no per-request
  parameter** — every caller on day D wants the same forecast, and rebuilding it means
  re-running the expensive 240-day SF refit + 200-draw propagation for an identical
  result. → **Precompute daily, store rows in Postgres.** (This whole spec.)
- **The node explorer and what-if layer *do* carry a parameter** (an arbitrary node, an
  arbitrary counterfactual μ) → serve the day's **SF matrix + point-μ vector** and
  reconstruct slices server-side. Drivers ("top-K constraints around a point") are one
  such slice; a `−X·SF[c,:]` counterfactual is another that no stored panel can answer.
  → **Emit a compact per-day SF+μ artifact (§4a); do not materialize driver rows.**
- **Do not serve the GBM boosters / run the heads per request** — their day-D output is
  itself a fixed daily grid, so there's no per-request variation to justify dragging the
  model runtime + feature pipeline into the API.

This is why below: the panel goes to a table; the drivers do **not** — they fall out of
the SF+μ artifact on demand.

---

## 1. What already exists, and where it's thrown away

Inside `walk()` (`compute/mu/propagate.py:170`), for each backtest week `s`:

```python
draws = draw_congestion(wp, SF, hours, eps, n_draws, rng)   # (n_draws, H, N) float32
Y     = C_score.loc[hours, SF.columns].to_numpy(np.float32)  # realized, (H, N)
...
rows.append({..., **band_metrics(Y, draws)})                 # <- draws collapsed to scalars
```

`band_metrics` computes exactly the panel we want and reduces it to means:

```python
p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)      # each (H, N)
```

- **Node axis** `N` = `SF.columns` — the settlement points the SF map carries *that week*
  (varies week to week; that is expected and must be preserved, not unioned/filled).
- **Hour axis** `H` = `hours` (`M_score.index ∩ C_score.index`, tz-aware UTC).
- **Units / sign** = congestion in the `C = −μ·SFᵀ` convention, $/MWh, same as `Y`.

After `band_metrics` returns, `draws` and the percentiles are freed. The fix is to tee
the percentiles out before they're discarded.

---

## 2. Design principles

1. **Do not perturb existing outputs.** `walk()` must still return the identical
   weekly-metrics DataFrame; `mu_bands_weekly.csv`, `r5()`, and the CLI's default
   behavior are unchanged. Emission is opt-in via a new flag.
2. **Flat, vocab-coded npz — not parquet, not dense arrays.** The repo does not use
   parquet; it stores panels as npz with a string vocab + int code (see
   `mu_model.save_preds`/`load_preds`: `key_vocab` + `key_code`). Reuse that idiom
   exactly. The node set (`SF.columns`) is ragged across weeks, so store **flat 1-D
   columns**, not a dense `(T, N, 3)` array that would force a union-and-fill:
   `ts` (int64 µs), `sp_code` (+ `sp_vocab`), `p10`, `p50`, `p90`, `point`. This is
   compact, matches the codebase, and unpacks straight into the `forecast_nodal` rows.
3. **Point forecast + drivers are deterministic — compute them separately from draws.**
   The median of 200 Bernoulli-sampled draws is noisy and not the model's point
   estimate. The point estimate is `E[μ] = P(bind)·E[μ|bind]` pushed through SF
   (`mu_from_preds` in `score.py`), which also decomposes cleanly into per-constraint
   contributions for the driver list. Reuse the `P`, `MU`, `SFm` arrays already
   materialized in `draw_congestion`.
4. **Drivers are reconstructed on demand, not stored (§0).** The node explorer's core
   interaction — click an SP → the top-K constraints driving it — is a slice of the day's
   SF matrix against the point-μ vector. Rather than materialize ~240k driver rows/day (or
   ~75M across the backtest), emit a compact **per-day SF + point-μ artifact** (§4a) and
   compute top-K (and counterfactuals) server-side when a node is clicked. The
   `--drivers` flag remains for offline/debug materialization on curated days only.

---

## 3. The refactor: one shared per-window function

Extract the per-week body of `walk()` into a function both the backtest and the daily
production job call. This is the structural change; the emission rides on it.

```python
@dataclass
class NodalPanel:
    ts: np.ndarray            # (H,)  tz-aware UTC hours
    settlement_points: np.ndarray   # (N,) = SF.columns
    p10: np.ndarray           # (H, N) float32
    p50: np.ndarray           # (H, N)  median of draws
    p90: np.ndarray           # (H, N)
    point: np.ndarray         # (H, N)  deterministic E[μ]·SF  (§4)
    sf_r2: np.ndarray | None  # (N,)    per-SP fit R² from the SF regression, if available

def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    eps: np.ndarray, n_draws: int, rng: np.random.Generator,
    *, want_panel: bool = False,
) -> tuple[dict | None, NodalPanel | None]:
    """Fit SF on [s-WINDOW_DAYS, s), score/draw over [s, end). Returns the
    weekly-metrics row (as today) and, when want_panel, the nodal panel."""
```

- `walk()` becomes: build `eps`/`SF`/`hours` as today, call `propagate_window(...,
  want_panel=emit)`, append the metrics row (unchanged), and — if `emit` — stream the
  panel to the sink (§5). **The metrics row must be byte-identical to today's** when
  `want_panel=False`; guard this with the existing `mu_bands_weekly.csv` as a golden
  file (§7).
- The panel's `p10/p50/p90` come from the *same* `np.percentile(draws, QUANTILES,
  axis=0)` call `band_metrics` uses — factor it so both read one computation, so the
  served p50 and the scored p50 can never diverge.

---

## 4. Deterministic point forecast + drivers (cheap, reuses existing arrays)

`draw_congestion` already builds `P` (H,K), `MU` (H,K), `SFm` (K,N). Add a deterministic
branch (no sampling):

```python
E_mu   = P * MU                       # (H, K)  E[μ] = P(bind)·E[μ|bind]
point  = -(E_mu @ SFm)                # (H, N)  the point congestion forecast
# per-node contributions for hour h:  contrib[h][k, n] = -E_mu[h,k] * SFm[k, n]
```

- **`point`** is the deterministic served headline value; store it alongside p50 in the
  panel table (they differ — p50 is the sampling median, `point` is the model's
  expectation).

### 4a. The per-day SF + μ artifact (powers drivers + what-if on demand)

Instead of materializing driver rows, `forecast_day` emits, per delivery day D, the two
objects the interactive endpoints reconstruct from:

- **`SF`** — the fitted shift-factor matrix used for D (`SF.index` = constraint keys,
  `SF.columns` = SPs). Store flat/vocab-coded npz (mirrors §2.2), or a per-day DB blob.
  ~1–2k constraints × ~1k SPs; dense float32 ≈ 4–8 MB, smaller if thresholded.
- **`E_mu`** — the point-μ vector `P(bind)·E[μ|bind]`, `(24h × K)`, same key vocab. ~100k
  floats.

Then the server computes, on request:
- **`/forecast/drivers?ts&sp`** → top-K constraints for node `sp` at `ts`:
  `contrib[k] = −E_mu[ts,k]·SF[k,sp]`, sort by `|contrib|`, return k. Signed — positive vs
  negative tells the trader whether the constraint *raises or lowers* that node's
  congestion. One column slice + top-k, sub-ms.
- **`/forecast/whatif?constraint&mu`** (future) → `−mu·SF[constraint,:]` = the nodal
  response to a hypothetical bind. No stored panel can answer this; the SF+μ artifact can.

**Guardrail (handoff §4/§5.2):** identifiability is unsolved and grouping did not fix it
— a single constraint's SF can flip between refits inside a co-binding block. Return
drivers with their refit-to-refit stability, and lead the explorer with the stable
unsigned exposure magnitude (`max_c|SF|`); the signed per-constraint list is the caveated
detail, not the headline.

`point`, the SF+μ artifact, and the driver decomposition all fall out of the `P`, `MU`,
`SFm` arrays already in hand — no second SF multiply, and nothing to store per-node.

---

## 5. Emission targets — npz artifact and/or Postgres

Serving reads from Postgres (the IBP/meta endpoints already do), so **the DB is the
sink that "easier serving" points at.** The npz artifact is the portable, idiomatic
offline form and the backtest bulk. Support both from one accumulator; they are the same
`NodalPanel` rows written two ways.

**(a) Offline npz artifact (flat, vocab-coded — §2.2).**
- Flag `--nodal-out PATH.npz` on `walk`'s CLI. Accumulate flat columns
  (`ts, sp_code, p10, p50, p90, point`) + `sp_vocab`, streaming per week so peak memory
  is one week (~2 MB of percentiles, not the 45-week concat). `week` retained as a column
  for the historic slider.
- Provide `load_nodal(path)` as the inverse (mirror `load_preds`), and a one-line
  `nodal_to_db(npz, conn)` loader that `COPY`s it into `forecast_nodal`.
- Drivers off by default here; full-history drivers are ~75M rows — don't (§2.4).
- This artifact backs the Phase-4 historic slider and seeds `forecast_nodal` in bulk.

**(b) Postgres — primary for serving.**
- Flag `--to-db` (or run `forecast_day` directly) writes the `forecast_nodal` panel for
  the delivery day(s) via `psycopg` `COPY`, then upserts the `forecast_current` pointer
  (§7). The API resolves that pointer per request — the same DB-pointer-resolved-on-read
  pattern the codebase already uses, but this feature owns its own table and pointer (no
  dependency on the legacy symlink/`compute.promote` path).
- For a single production day (`forecast_day`, spec-phase2b-forecast-day), write straight to
  the DB — the panel is small (24k rows) and needs no intermediate file. The SF+μ
  artifact (§4a) is written alongside for the interactive endpoints; **driver rows are
  not written** (§0).

**(c) Per-day SF + μ artifact (§4a).** Emitted by `forecast_day` for the served day so
`/forecast/drivers` and `/forecast/whatif` reconstruct on demand. Small (single-digit
MB/day); stored as npz under the run dir and/or a DB blob keyed by `(run_id, delivery_date)`.

Recommendation: **npz is the artifact of record; the DB is the serving substrate.** Write
the panel to the DB directly in production, keep npz→DB as the bulk path so backtest and
production converge on the same table, and ship the SF+μ artifact so drivers cost storage
once per day, not once per node-hour.

---

## 6. DB schema (matches serving plan §4.2)

```sql
CREATE TABLE forecast_nodal (
    run_id           text        NOT NULL,
    delivery_date    date        NOT NULL,
    ts               timestamptz NOT NULL,
    settlement_point text        NOT NULL,
    p10  real, p50 real, p90 real,
    point real,
    PRIMARY KEY (run_id, ts, settlement_point)
);
-- No forecast_drivers table: drivers are reconstructed on read from the SF+μ
-- artifact (§0, §4a). The artifact is stored per (run_id, delivery_date) as an npz
-- under the run dir and/or a bytea blob:
CREATE TABLE forecast_sf_artifact (
    run_id        text NOT NULL,
    delivery_date date NOT NULL,
    sf_npz        bytea NOT NULL,      -- flat/vocab-coded SF + E_mu for the day
    PRIMARY KEY (run_id, delivery_date)
);
CREATE TABLE forecast_current (        -- this feature's own pointer (not the legacy one)
    layer         text PRIMARY KEY,    -- 'ercot'
    run_id        text NOT NULL,
    promoted_at   timestamptz NOT NULL DEFAULT now()
);
```
Bulk-load `forecast_nodal` from the npz via `COPY`; the per-SP `sf_r2` (fit confidence)
rides on the existing IBP diagnostics, not this table.

---

## 7. Production vs backtest — the differences that matter

| | Backtest (`walk`) | Production (`forecast_day`) |
|---|---|---|
| Scored window | `[s, s+7d)` | `[D, D+1d)` = 24 h |
| Preds source | `mu_preds.npz` (walk-forward) | daily μ-model inference for D |
| Residual pool `eps` | prior scored weeks only | **all** validated backtest weeks (fixed pool) |
| SF fit window | `[s−240d, s)` | `[D−240d, D)`, ending strictly before D |
| Realized `Y` | available | absent until D+1 → panel has no coverage row |

⚠ **Cutoff discipline (serving plan §7, handoff §3/§10).** In production the SF fit
window and every μ covariate must be pinned at **DAM close (10:00 CT, D−1)**. The
backtest reuses `mu_preds.npz` which was already built walk-forward, so the offline
emission inherits the honest cutoff for free — but `forecast_day` reads live inputs and
needs its own two-sided leakage test. Do not reuse `features.history_cutoff` blindly
for the production preds; that guarantee is DAM-vintage-specific.

---

## 8. CLI

```
python -m compute.mu.propagate \
  --preds /compute/mu/mu_preds.npz \
  --scores /compute/mu/mu_score_weekly.csv \
  --out    /compute/mu/mu_bands_weekly.csv    # unchanged; still the default deliverable
  --nodal-out /compute/mu/forecast_nodal.npz  # NEW: emit the panel (flat, vocab-coded)
  --to-db                                      # NEW: also COPY into forecast_nodal + flip pointer
  --drivers                                    # NEW: also emit drivers (curated only in backtest)
```
With none of the new flags, behavior and outputs are identical to today.

## 9. Size / memory

- Percentiles per week: `(3, H≈168, N≈1000)` float32 ≈ 2 MB. Streamed, never concatenated.
- Full backtest panel, flat npz: ~45 wk × 168 h × ~1000 SP ≈ **7.5M rows** ×
  (p10/p50/p90/point) float32 ≈ **120 MB** on disk — trivial, and `COPY`s into the DB fast.
- Production day: 24 h × ~1000 SP = **24k nodal rows** per day, plus one **SF+μ artifact
  ~4–8 MB**. No driver rows stored (§0) — drivers are a read-time slice of the artifact.
- `draws` peak `(200,168,1000)` float32 ≈ 134 MB already tolerated today; unchanged.

## 10. Verification

- **Golden-file regression:** run with `--nodal-out` and confirm `mu_bands_weekly.csv`
  is byte-identical to a pre-change baseline — proves the metrics path is untouched.
- **Consistency:** the emitted per-week `p50`, re-reduced (`nanmean`) exactly reproduces
  `band_metrics`' `coverage80`/`band_width` for that week (same percentile call).
- **Alignment:** panel node axis == `SF.columns`; hour axis == `hours`; a spot node's
  `point` equals `-(E_mu @ SF)[:, n]` recomputed independently.
- **Determinism:** fixed `--seed` reproduces p10/p50/p90 bit-for-bit.
- **Production leakage:** `forecast_day(D)` with the SF window forced past DAM close must
  fail the two-sided lookahead test (build it before the first live publish).

## 11. Open choices for the implementer

- **Driver k** (default 10) — a read-time `LIMIT`, so it's free to change; not baked into storage.
- **SF+μ artifact: npz-on-disk vs DB bytea?** Disk under the run dir is simplest; a DB
  blob keeps serving single-substrate. Pick per how the API reads the run dir today.
- **npz→DB now, or npz-only for backtest?** Recommend wiring the `nodal_to_db` loader
  now so backtest and production land in the same `forecast_nodal` table — it makes the
  Phase-4 historic slider serve from the same endpoint as tomorrow's forecast.
- **Store `point` separately from `p50`?** Yes (they differ; §4). Serve `point` as the
  headline value, `p50` for the band's center, `p10/p90` for the band.
- **`sf_r2` provenance** — pull from the SF fit if `implied_shift_factors` exposes per-SP
  R²; otherwise defer fit-confidence to the IBP diagnostics already served.
