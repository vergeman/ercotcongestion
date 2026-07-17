"""Commit 5 — sample the heads, push them through the map, read the bands. Then
the R5 verdict, against the bar as written.

The point forecast (commit 4) answers "how sure are you of the number" by
turning the two heads back into the distribution they were always implicitly
describing:

    for each draw d:
        bind[k,h] ~ Bernoulli(p_bind[k,h])              # head 1
        μ[k,h]    ~ E[μ|bind][k,h] · exp(ε),  ε ~ residuals   # head 2 + spread
        C[·,h]    = −μ[·,h] · SF                        # the map, unchanged
    P10/P50/P90 = percentiles of C across draws

**Where the spread comes from, and why not from the training window.** Head 2 is a
GBM; its residuals *on its own training window* are the residuals of a model that
has already fitted them, so they are too small, and bands built from them would be
confidently narrow — the exact failure the 0085 summary calls "a confident wrong
band is worse than an honest wide one". Instead the residual pool for week `s` is
the log-space error the model made on **the weeks it already scored, all strictly
before `s`** — genuinely out-of-sample errors, from the same model, on the same
market. Week 1 therefore has no pool and gets no bands: 46 weeks are scored, 45
carry bands, and that is stated rather than papered over.

**The known understatement.** Head 1 is sampled independently per constraint. The
constraints are collinear (0083 — that is *why* R3 failed), so the true joint
binding set is far more correlated than independent Bernoullis, and a sum of
independent draws has too thin a tail. This makes coverage a *measurement*, not a
formality: if the bands are too narrow, this is the first place to look. Reported,
not assumed away.

    docker compose run --rm compute python -m compute.mu.propagate \
      --preds /compute/mu/mu_preds.npz --out /compute/mu/mu_bands_weekly.csv

"""
from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from compute.mu.score import (
    LAM, MIN_HOURS, REFIT_DAYS, RTC_B, STD_FLOOR, WINDOW_DAYS, score_matrix,
    weeks_from_preds,
)
from compute.sf.fit import implied_shift_factors

log = logging.getLogger("compute.mu.propagate")

N_DRAWS = 200
DRAW_CHUNK = 25          # cap peak memory; percentiles need every draw kept
RESID_CAP = 500_000      # the pool is sampled from, not enumerated
QUANTILES = (10, 50, 90)


@dataclass
class NodalPanel:
    """The per-SP forecast panel `walk()` already computes and discards.

    The node axis is ragged week to week — it is exactly `SF.columns` for the
    week's fit, never unioned or filled — so a panel is one window's grid, not
    a dense cross-week array. `point` is the deterministic `E[μ]·SF` (§4), which
    is NOT the sampling median `p50`; both are stored because they differ.
    """
    ts: np.ndarray                  # (H,)   tz-aware UTC hours = `hours`
    settlement_points: np.ndarray   # (N,)   = SF.columns
    p10: np.ndarray                 # (H, N) float32
    p50: np.ndarray                 # (H, N) float32  median of draws
    p90: np.ndarray                 # (H, N) float32
    point: np.ndarray               # (H, N) float32  deterministic E[μ]·SF
    sf_r2: np.ndarray | None        # (N,)   per-SP SF fit R², if available


def _epoch_us(idx) -> np.ndarray:
    """int64 UTC microseconds, matching `mu_model.save_preds`' timestamp encoding.

    Microseconds (not ns) because pandas 3 makes `us` the default resolution, so
    an ns round-trip returns a different dtype and silently fails an index
    compare; the data is hourly, so there is no precision to lose either way.
    """
    di = pd.DatetimeIndex(idx)
    if di.tz is not None:
        di = di.tz_convert("UTC").tz_localize(None)
    return di.to_numpy("datetime64[us]").astype("int64")


class _NodalAccumulator:
    """Streams `NodalPanel`s to flat vocab-coded columns one window at a time.

    The node axis is ragged week to week (§9), so weeks are never densified into
    a common `(T, N, 3)` array: each panel's `(H, N)` grids are raveled to
    `(H*N,)` rows and its SPs mapped onto one growing `sp_vocab` — the same
    `key_vocab` + `key_code` idiom `mu_model.save_preds` uses to keep repeated
    strings out of the file. Peak memory is one week of percentiles (~2 MB), not
    the 45-week concat.
    """

    def __init__(self) -> None:
        self._sp_code: dict[str, int] = {}
        self._buf: dict[str, list[np.ndarray]] = {
            k: [] for k in ("ts", "sp_code", "p10", "p50", "p90", "point", "week")}

    def add(self, panel: NodalPanel, week: pd.Timestamp) -> None:
        H, N = len(panel.ts), len(panel.settlement_points)
        code = np.fromiter(
            (self._sp_code.setdefault(str(sp), len(self._sp_code))
             for sp in panel.settlement_points),
            dtype=np.int32, count=N)
        ts_us = _epoch_us(panel.ts)                          # (H,)
        week_us = int(_epoch_us(pd.DatetimeIndex([week]))[0])
        # Row r = h*N + n: `ravel` is C-order (hour-major), so `repeat` the hours
        # and `tile` the SP codes to line the axes up with the percentile grids.
        b = self._buf
        b["ts"].append(np.repeat(ts_us, N))
        b["sp_code"].append(np.tile(code, H))
        b["p10"].append(panel.p10.ravel())
        b["p50"].append(panel.p50.ravel())
        b["p90"].append(panel.p90.ravel())
        b["point"].append(panel.point.ravel())
        b["week"].append(np.full(H * N, week_us, dtype=np.int64))

    def save(self, path: str) -> None:
        cols = {k: (np.concatenate(v) if v else np.empty(0, np.int64))
                for k, v in self._buf.items()}
        vocab = np.array(list(self._sp_code), dtype=object).astype("U")
        save_nodal(path, cols, vocab)


def save_nodal(path: str, cols: dict[str, np.ndarray], sp_vocab: np.ndarray) -> None:
    """Write the flat nodal panel as a compressed .npz.

    Same encoding as `mu_model.save_preds`: int64 UTC-µs `ts`/`week`, an int32
    `sp_code` against a string `sp_vocab` (never a string per row — at ~7.5M rows
    that is a gigabyte of repeated SP names), float32 percentiles + `point`.
    """
    np.savez_compressed(
        path,
        ts=cols["ts"].astype("int64"),
        sp_code=cols["sp_code"].astype("int32"),
        sp_vocab=np.asarray(sp_vocab, dtype=object).astype("U"),
        p10=cols["p10"].astype("float32"),
        p50=cols["p50"].astype("float32"),
        p90=cols["p90"].astype("float32"),
        point=cols["point"].astype("float32"),
        week=cols["week"].astype("int64"),
    )


def load_nodal(path: str) -> pd.DataFrame:
    """Inverse of `save_nodal`: tz-aware UTC `ts`/`week`, decoded
    `settlement_point`, and the p10/p50/p90/point columns. Round-trips exactly —
    see the test."""
    z = np.load(path, allow_pickle=False)
    vocab = z["sp_vocab"]
    return pd.DataFrame({
        "ts": pd.to_datetime(z["ts"], unit="us", utc=True),
        "settlement_point": vocab[z["sp_code"]],
        "p10": z["p10"], "p50": z["p50"], "p90": z["p90"], "point": z["point"],
        "week": pd.to_datetime(z["week"], unit="us", utc=True),
    })


@dataclass
class SfMuArtifact:
    """The per-day SF matrix + point-μ vector the interactive endpoints reconstruct
    drivers / what-if from (§4a) — shipped instead of ~240k materialized driver
    rows/day. `SF` is (K constraints × N SPs); `E_mu` is (H hours × K) on the SAME
    constraint-key vocab as `SF.index`, so a node's drivers at `ts` are the plain
    aligned product `contrib[k] = −E_mu.loc[ts, k]·SF.loc[k, sp]`, and the stable
    unsigned headline is `SF.loc[:, sp].abs().max()` (the sign-flip guardrail, §4a).
    """
    SF: pd.DataFrame        # index = constraint keys, columns = settlement points
    E_mu: pd.DataFrame      # index = tz-aware UTC hours, columns = constraint keys


def build_sf_mu_artifact(SF: pd.DataFrame, E_mu: pd.DataFrame) -> bytes:
    """Serialize the day's `SF` + `E_mu` to a flat vocab-coded npz blob (§4a).

    Same idiom as `save_nodal`/`save_preds`: the constraint keys and SPs are stored
    once as string vocabs and the matrices as dense float32 on those axes — the
    whole day is one compact object (~1–2k constraints × ~1k SPs, single-digit MB),
    not a per-node-hour row explosion. `E_mu` is aligned onto `SF.index` so both
    carry one shared key vocab and the read-time `−E_mu·SF` decomposition needs no
    realignment. Returns the npz bytes for the `forecast_sf_artifact.sf_npz` bytea;
    `save_sf_mu` writes the identical bytes to disk. Round-trips via `load_sf_mu`.
    """
    E = E_mu.reindex(columns=SF.index)          # one shared constraint-key vocab
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        key_vocab=np.asarray(SF.index, dtype=object).astype("U"),
        sp_vocab=np.asarray(SF.columns, dtype=object).astype("U"),
        sf=SF.to_numpy(np.float32),                          # (K, N)
        ts=_epoch_us(E.index),                               # (H,) UTC µs
        e_mu=E.to_numpy(np.float32),                         # (H, K)
    )
    return buf.getvalue()


def save_sf_mu(path: str, SF: pd.DataFrame, E_mu: pd.DataFrame) -> None:
    """`build_sf_mu_artifact` to disk — the on-disk artifact of record (§5c);
    identical bytes to the DB bytea, so either sink is authoritative."""
    with open(path, "wb") as fh:
        fh.write(build_sf_mu_artifact(SF, E_mu))


def load_sf_mu(src) -> SfMuArtifact:
    """Inverse of `build_sf_mu_artifact`: accepts a filesystem path or the raw npz
    `bytes` (the DB bytea) and returns the SF/E_mu frames on their shared
    constraint-key vocab. Round-trips exactly — see the test."""
    z = np.load(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src,
                allow_pickle=False)
    keys = z["key_vocab"]
    return SfMuArtifact(
        SF=pd.DataFrame(z["sf"], index=keys, columns=z["sp_vocab"]),
        E_mu=pd.DataFrame(z["e_mu"],
                          index=pd.to_datetime(z["ts"], unit="us", utc=True),
                          columns=keys),
    )


DRIVERS_K = 10                    # read-time top-k; a LIMIT, free to change (§11)
DRIVERS_MAX_DAYS = 14             # curated debug set only, never full history (§2.4)


def node_drivers(art: SfMuArtifact, sp: str, ts, k: int = DRIVERS_K) -> pd.DataFrame:
    """The `/forecast/drivers` read-time slice (§4a): the top-k constraints
    driving node `sp` at `ts`. `contrib[k] = −E_mu[ts,k]·SF[k,sp]`, sorted by
    |contrib|, signed so the sign tells whether a constraint *raises or lowers*
    that node's congestion. `exposure` is the stable unsigned headline
    `max_c|SF[:,sp]|` the explorer leads with — a single constraint's SF can
    flip sign between refits inside a co-binding block, so the signed list is
    the caveated detail (§4a).
    """
    contrib = -(art.E_mu.loc[pd.Timestamp(ts)] * art.SF[sp])
    contrib = contrib[contrib != 0.0]         # only constraints the map ties to sp
    top = contrib.reindex(contrib.abs().sort_values(ascending=False).index).head(k)
    return pd.DataFrame({
        "ts": pd.Timestamp(ts), "settlement_point": sp,
        "constraint": top.index.to_numpy(),
        "contrib": top.to_numpy(dtype=float),
        "abs_contrib": top.abs().to_numpy(dtype=float),
        "exposure": float(art.SF[sp].abs().max()),
    })


def materialize_drivers(art: SfMuArtifact, k: int = DRIVERS_K,
                        sps=None) -> pd.DataFrame:
    """Offline/debug top-k driver rows for one day's artifact — curated days ONLY.

    This is the ~240k-row/day expansion `/forecast/drivers` avoids by slicing on
    read (§0); across the full backtest it would be ~75M rows, which is exactly why
    the `--drivers` CLI guards to an explicit curated day set (`parse_curated_days`)
    and never runs full history. Loops `node_drivers` over every (ts, sp)."""
    sps = list(art.SF.columns) if sps is None else list(sps)
    frames = [node_drivers(art, sp, ts, k) for ts in art.E_mu.index for sp in sps]
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts", "settlement_point", "constraint", "contrib",
                 "abs_contrib", "exposure"]))


def parse_curated_days(spec: str | None) -> list[pd.Timestamp]:
    """Parse `--drivers` into an explicit, bounded set of curated delivery days.

    Accepts a comma-separated list of ISO dates (`2025-06-01,2025-07-15`) — an
    explicit enumeration only. A range/span (`a:b`), an empty spec, or more than
    `DRIVERS_MAX_DAYS` days all raise: driver materialization is curated debug
    output, never the full-history walk (§2.4, §5a)."""
    if spec is None or not spec.strip():
        raise ValueError("--drivers needs an explicit comma-separated day list, "
                         "e.g. 2025-06-01,2025-07-15 (curated debug only)")
    if ":" in spec:
        raise ValueError("--drivers takes explicit days, not a span 'a:b' — driver "
                         "rows are curated debug output, never a full-history run")
    days = [pd.Timestamp(t.strip()) for t in spec.split(",") if t.strip()]
    if not days:
        raise ValueError("--drivers day list is empty")
    if len(days) > DRIVERS_MAX_DAYS:
        raise ValueError(
            f"--drivers is for curated days (<= {DRIVERS_MAX_DAYS}), got "
            f"{len(days)} — that is not a curated set (§2.4, §5a)")
    return days


FORECAST_LAYER = "ercot"


def _delivery_dates(ts: pd.Series) -> pd.Series:
    """UTC calendar date of each tz-aware UTC hour — the `forecast_nodal`/
    `forecast_sf_artifact` `delivery_date` and the idempotency scope for a re-run.

    The whole stack below the API speaks UTC instants: every `interval_ts` is a
    true UTC instant (migration 17 repaired the CT-as-UTC drift), the API coerces
    to UTC, and the model slices the UTC-normalized index. `delivery_date` is
    therefore the UTC date, not the ERCOT CT operating day — a UTC day's 24 hours
    share one `delivery_date`, so a single-day write/scope is clean. (The DAM-close
    vintage cutoff in `features.py` stays a CT wall-clock event; that pins each
    covariate's *publication time* per interval and is independent of this label.)
    """
    return ts.dt.tz_convert("UTC").dt.date


def nodal_to_db(npz_path: str, conn, *, run_id: str,
                delivery_date=None) -> int:
    """Load a `save_nodal` panel and `COPY` it into `forecast_nodal` for `run_id`.

    Idempotent by delete-then-copy scoped to what is written, so a re-run replaces
    cleanly (spec §5b, phase2b §6): with `delivery_date` set, only that operating
    day for the run is cleared and only its rows land (the single-day production
    path); with it `None`, the whole run is cleared and every day in the npz is
    (re)written (the backtest bulk path). `delivery_date` is derived per row from
    the CT-local date of `ts`, so the same PK never both survives and reappears —
    collisions replace, not duplicate.

    Does NOT commit and does NOT touch the pointer — the caller flips
    `forecast_current` via `upsert_pointer` AFTER these rows land, so a reader
    never sees a half-written day. Returns the number of rows written.
    """
    target = pd.Timestamp(delivery_date).date() if delivery_date is not None else None
    df = load_nodal(npz_path)
    df = df.assign(delivery_date=_delivery_dates(df["ts"]))
    if target is not None:
        df = df[df["delivery_date"] == target]

    with conn.cursor() as cur:
        if target is not None:
            cur.execute(
                "DELETE FROM forecast_nodal WHERE run_id = %s "
                "AND delivery_date = %s", (run_id, target))
        else:
            cur.execute("DELETE FROM forecast_nodal WHERE run_id = %s", (run_id,))

    ts_iso = df["ts"].astype(str).to_numpy()          # ISO w/ +00:00 offset
    dd_iso = df["delivery_date"].astype(str).to_numpy()
    sp = df["settlement_point"].to_numpy()
    p10, p50, p90 = (df[c].to_numpy(np.float64) for c in ("p10", "p50", "p90"))
    point = df["point"].to_numpy(np.float64)

    def _f(v) -> float | None:                        # NaN percentile -> NULL
        return v if np.isfinite(v) else None

    sql = ("COPY forecast_nodal (run_id, delivery_date, ts, settlement_point, "
           "p10, p50, p90, point) FROM STDIN")
    n = len(df)
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for i in range(n):
            cp.write_row((run_id, dd_iso[i], ts_iso[i], sp[i],
                          _f(p10[i]), _f(p50[i]), _f(p90[i]), _f(point[i])))
    return n


def upsert_pointer(conn, layer: str, run_id: str) -> None:
    """Flip `forecast_current[layer] = run_id`. Call ONLY after the rows land —
    this feature's own pointer, mirroring `set_current_pointer` for the IBP map,
    never the legacy `implied_binding_proximity_current`."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_current (layer, run_id) VALUES (%s, %s) "
            "ON CONFLICT (layer) DO UPDATE "
            "SET run_id = EXCLUDED.run_id, promoted_at = now()",
            (layer, run_id))


def sf_artifact_to_db(conn, *, run_id: str, delivery_date, sf_npz: bytes) -> None:
    """Upsert the day's SF+μ npz blob into `forecast_sf_artifact` for
    `(run_id, delivery_date)`. Idempotent replace-in-place, the same discipline as
    `nodal_to_db` (0010): a re-run overwrites the day's blob, never appends. Does
    NOT commit — the caller owns the transaction."""
    dd = pd.Timestamp(delivery_date).date()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_sf_artifact (run_id, delivery_date, sf_npz) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, delivery_date) DO UPDATE "
            "SET sf_npz = EXCLUDED.sf_npz",
            (run_id, dd, sf_npz))


def persist_sf_mu_artifact(conn, SF: pd.DataFrame, E_mu: pd.DataFrame, *,
                           run_id: str, delivery_date, npz_dir: str | None = None,
                           ) -> bytes:
    """Build the day's SF+μ blob once and land it per `(run_id, delivery_date)`.

    Always upserts the `forecast_sf_artifact` bytea; also drops the identical npz
    under `npz_dir` when given (§5c — disk and DB hold the same bytes, either is
    authoritative). Idempotent replace per key; does NOT commit. Returns the blob so
    the caller can size/inspect it. `forecast_day` (phase2b) is the production
    caller; `--drivers` (below) is the offline one."""
    blob = build_sf_mu_artifact(SF, E_mu)
    if npz_dir is not None:
        dd = pd.Timestamp(delivery_date).date()
        with open(os.path.join(npz_dir, f"sf_mu_{run_id}_{dd.isoformat()}.npz"),
                  "wb") as fh:
            fh.write(blob)
    sf_artifact_to_db(conn, run_id=run_id, delivery_date=delivery_date, sf_npz=blob)
    return blob


def residual_pool(prior: pd.DataFrame, cap: int = RESID_CAP,
                  rng: np.random.Generator | None = None) -> np.ndarray:
    """Head 2's out-of-sample log-space errors on the weeks already behind us.

    Log space because head 2 fits `log1p(μ)` — μ spans $0.01 to $4,000 and an
    additive residual drawn from that would be meaningless at one end and absurd
    at the other. `expm1(log1p(μ̂) + ε)` keeps the draw positive and scales the
    spread with the level, which is how shadow prices actually behave.
    """
    b = prior[(prior["y_bind"] == 1) & prior["y_mu"].notna()]
    if b.empty:
        return np.array([], dtype=np.float32)
    eps = (np.log1p(b["y_mu"].to_numpy(np.float64))
           - np.log1p(np.clip(b["mu_gbm"].to_numpy(np.float64), 0, None)))
    eps = eps[np.isfinite(eps)].astype(np.float32)
    if len(eps) > cap:
        rng = rng or np.random.default_rng(0)
        eps = rng.choice(eps, size=cap, replace=False)
    return eps


def _wide(week_preds: pd.DataFrame, col: str, hours: pd.DatetimeIndex,
          cols: pd.Index) -> np.ndarray:
    w = week_preds.pivot_table(index="interval_ts", columns="key", values=col,
                               aggfunc="mean")
    return w.reindex(index=hours, columns=cols).fillna(0.0).to_numpy(np.float32)


def draw_congestion(week_preds: pd.DataFrame, SF: pd.DataFrame,
                    hours: pd.DatetimeIndex, eps: np.ndarray,
                    n_draws: int = N_DRAWS,
                    rng: np.random.Generator | None = None,
                    *, want_point: bool = False,
                    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """(draws × hours × nodes) of sampled nodal congestion.

    With `want_point`, also return the deterministic point forecast
    `point = −(E[μ]·SF)` where `E[μ] = P(bind)·E[μ|bind]` (§4). It reuses the
    `P`/`MU`/`SFm` arrays already built here — no sampling, no second SF
    multiply — and is the model's expectation, distinct from the draws' median.
    """
    rng = rng or np.random.default_rng(0)
    cols = SF.index                                   # only keys the map carries
    P = _wide(week_preds, "p_bind", hours, cols)      # (H, K)
    MU = _wide(week_preds, "mu_gbm", hours, cols)     # (H, K) = E[μ | bind]
    SFm = SF.to_numpy(np.float32)                     # (K, N)
    H, K, N = len(hours), len(cols), SF.shape[1]

    out = np.empty((n_draws, H, N), dtype=np.float32)
    log_mu = np.log1p(np.clip(MU, 0, None))
    for lo in range(0, n_draws, DRAW_CHUNK):
        d = min(DRAW_CHUNK, n_draws - lo)
        bind = rng.random((d, H, K), dtype=np.float32) < P            # head 1
        e = (rng.choice(eps, size=(d, H, K)) if len(eps)
             else np.zeros((d, H, K), np.float32))                    # spread
        mu = np.expm1(log_mu[None] + e) * bind                        # head 2
        np.clip(mu, 0, None, out=mu)          # a shadow price is never negative
        out[lo:lo + d] = -(mu.reshape(d * H, K) @ SFm).reshape(d, H, N)
    if want_point:
        E_mu = P * MU                                 # (H, K) E[μ]=P(bind)·E[μ|bind]
        point = -(E_mu @ SFm).astype(np.float32)      # (H, N) same sign as draws
        return out, point
    return out


def band_metrics(Y: np.ndarray, p10: np.ndarray, p50: np.ndarray,
                 p90: np.ndarray) -> dict:
    """Coverage FIRST, then skill. A band that misses is not a narrower band, it
    is a wrong one, and P50 skill next to broken coverage is a sales pitch.

    Percentiles are computed once by the caller (`np.percentile(draws,
    QUANTILES, axis=0)`) and passed in, so the scored p50 and the served p50
    can never diverge — both read the same array."""
    inside = (Y >= p10) & (Y <= p90)
    m = {
        "coverage80": float(np.nanmean(inside)),      # target 0.80
        "band_width": float(np.nanmean(p90 - p10)),
        "pinball": float(np.nanmean([_pinball(Y, q, p / 100)
                                     for q, p in zip((p10, p50, p90), QUANTILES)])),
        **score_matrix(Y, p50),                       # P50 is the point forecast
    }
    return m


def _pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.nanmean(np.maximum(tau * d, (tau - 1) * d)))


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    eps: np.ndarray, n_draws: int, rng: np.random.Generator,
    *, want_panel: bool = False, want_sf_mu: bool = False,
    forward_hours: pd.DatetimeIndex | None = None,
) -> tuple[dict | None, NodalPanel | None, pd.DataFrame | None, pd.DataFrame | None]:
    """One window, shared by the backtest and `forecast_day`.

    Fit SF on ``[s−WINDOW_DAYS, s)``, score/draw over ``[s, end)``, and build the
    weekly-metrics row exactly as `walk()` did. Returns ``(row, None, None,
    None)`` normally; with ``want_panel`` also the `NodalPanel` teed from the same
    draws and the same `np.percentile` call the metrics use; with ``want_sf_mu``
    also the window's fitted ``SF`` (K×N) and ``E_mu`` (H×K on ``SF.index``) for the
    SF+μ artifact (§4a). ``(None, None, None, None)`` on any skip (empty fit window,
    empty SF, no scored hours) — the caller's `continue`.

    **Forward mode** (`forward_hours` given — `forecast_day` for a delivery day D
    with no realized congestion yet, §3.2): the scored hours are the caller's
    delivery-day calendar (D's 24 intervals) rather than ``M_score ∩ C_score``,
    no realized ``Y`` is read (``C`` is never indexed on the score side, so a
    ``C`` that is empty/absent for D cannot crash the panel), and ``row`` is
    ``None`` (no `band_metrics` without an outcome). The fit window, the SF fit,
    and the `want_panel`/`want_sf_mu` tees are byte-identical to the backtest.
    """
    forward = forward_hours is not None
    lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
    M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
    C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
    if M_fit.empty:
        return None, None, None, None
    SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                               standardize=True, std_floor=STD_FLOOR)
    if SF.empty:
        return None, None, None, None

    M_score = M.loc[(M.index >= s) & (M.index < end)]
    if forward:
        hours = forward_hours
    else:
        C_score = C.loc[(C.index >= s) & (C.index < end)]
        hours = M_score.index.intersection(C_score.index)
    if not len(hours):
        return None, None, None, None

    wp = wp[wp["key"].isin(SF.index)]

    mass_all = float(M_score.abs().to_numpy(float).sum())
    cov_cols = M_score.columns.intersection(SF.index)
    sf_coverage = (float(M_score[cov_cols].abs().to_numpy(float).sum())
                   / mass_all if mass_all > 0 else np.nan)

    panel = None
    if want_panel:
        draws, point = draw_congestion(wp, SF, hours, eps, n_draws, rng,
                                       want_point=True)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)
        panel = NodalPanel(
            ts=hours.to_numpy(),
            settlement_points=SF.columns.to_numpy(),
            p10=p10.astype(np.float32), p50=p50.astype(np.float32),
            p90=p90.astype(np.float32), point=point,
            sf_r2=None,          # implied_shift_factors exposes no per-SP R² (§11)
        )
    else:
        draws = draw_congestion(wp, SF, hours, eps, n_draws, rng)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)

    E_mu = None
    if want_sf_mu:
        # E[μ]=P(bind)·E[μ|bind] on SF.index — the same arrays draw_congestion builds
        # (§4a), rebuilt here (two cheap pivots) so the return needs no draws.
        P = _wide(wp, "p_bind", hours, SF.index)
        MU = _wide(wp, "mu_gbm", hours, SF.index)
        E_mu = pd.DataFrame(P * MU, index=hours, columns=SF.index)

    row = None
    if not forward:
        # hours ⊆ C_score.index ⊆ C.index, so this selects the same rows in the
        # same order as the pre-forward `C_score.loc[hours]`, byte-identical.
        Y = C.loc[hours, SF.columns].to_numpy(np.float32)
        row = {"week": s, "n_hours": len(hours), "n_nodes": SF.shape[1],
               "n_resid": len(eps), "sf_coverage": sf_coverage,
               **band_metrics(Y, p10, p50, p90)}
    return row, panel, (SF if want_sf_mu else None), E_mu


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         n_draws: int = N_DRAWS, seed: int = 0,
         nodal_out: str | None = None,
         curated: dict | None = None) -> pd.DataFrame:
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()
    weeks = weeks_from_preds(preds)
    rng = np.random.default_rng(seed)
    log.info("propagating %d weeks × %d draws (week 1 has no residual pool → no "
             "bands)", len(weeks), n_draws)

    # Emitting the panel only tees the arrays already computed — same rng draws,
    # so the metrics row (and `mu_bands_weekly.csv`) is byte-identical either way.
    sink = _NodalAccumulator() if nodal_out else None
    # `curated` is {delivery_date: None} for the --drivers days; the walk fills the
    # ones whose operating day falls inside a scored window with that day's SF+μ
    # artifact (§4a). None ⟹ no artifact requested (the common path, no extra work).
    want_sf_mu = bool(curated)
    by_week = dict(tuple(preds.groupby("week", sort=False)))
    rows: list[dict] = []
    t0 = time.perf_counter()
    for i, s in enumerate(weeks):
        # The pool is every week the model has ALREADY scored — out-of-sample
        # errors, strictly in the past. Empty on week 1, by construction.
        prior = preds[preds["week"] < s]
        eps = residual_pool(prior, rng=rng)
        if not len(eps):
            log.info("  week %2d/%d %s  no residual pool yet — skipped",
                     i + 1, len(weeks), s.date())
            continue

        end = s + pd.Timedelta(days=REFIT_DAYS)
        row, panel, SF, E_mu = propagate_window(
            s, end, M, C, by_week[s], eps, n_draws, rng,
            want_panel=sink is not None, want_sf_mu=want_sf_mu)
        if row is None:
            continue

        rows.append(row)
        if sink is not None:
            assert panel is not None      # want_panel=True ⟹ panel built when row is
            sink.add(panel, s)
        if want_sf_mu and E_mu is not None:
            # Slice the week's E_mu to each requested operating day and pair it with
            # this window's SF — the per-day artifact forecast_day would emit.
            dd = _delivery_dates(pd.Series(E_mu.index, index=E_mu.index))
            for day in list(curated):
                mask = (dd == day).to_numpy()
                if mask.any():
                    curated[day] = SfMuArtifact(SF=SF, E_mu=E_mu.loc[mask])
        done, el = i + 1, time.perf_counter() - t0
        log.info("  week %2d/%d %s  cov80 %.3f  P50 R2 %+.3f  eta %.0fm",
                 done, len(weeks), s.date(), rows[-1]["coverage80"],
                 rows[-1]["pooled_r2"], (el / done) * (len(weeks) - done) / 60)
    if sink is not None and nodal_out is not None:
        sink.save(nodal_out)
        log.info("wrote nodal panel → %s", nodal_out)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# R5 — the verdict, against the bar as written
# --------------------------------------------------------------------------

def gate(r2: float, spearman: float, sign: float, topdec: float) -> str:
    """§5.5, transcribed. Either currency can clear a row ("either bar clears").

    Written as code so the bar cannot drift while being read. It was fixed before
    the numbers existed and is not edited now that they do — that is the whole
    point of pre-registering it. If this function and the doc ever disagree, the
    doc wins and this is the bug.
    """
    if r2 >= 0.5 or (spearman >= 0.70 and sign >= 0.85):
        return "FORECAST PRODUCT"
    if (0.3 <= r2 < 0.5) or (0.60 <= spearman < 0.70 and topdec >= 0.60):
        return "SCREENING TOOL"
    if r2 < 0.3 or (spearman < 0.60 and topdec <= 0.649):
        return "NOT THE PRODUCT"
    return "BETWEEN BARS — read the table, do not round"


def existence_test(model: dict, persistence: dict) -> tuple[bool, str]:
    """"Beat persistence in the screening currency" (handoff §5.5).

    Relative, so persistence must be the one measured in THIS harness — the
    0.581/0.771/0.649 in the handoff came from the old 60-day, λ=0.1 map, and
    grading against those would be grading against a different experiment.
    """
    keys = ["rank_spearman", "sign_agree", "topdecile_hit"]
    wins = {k: model[k] > persistence[k] for k in keys}
    detail = "  ".join(
        f"{k.split('_')[0]} {model[k]:.3f} vs {persistence[k]:.3f} "
        f"{'WIN' if wins[k] else 'LOSS'}" for k in keys)
    return all(wins.values()), detail


def r5(score_csv: pd.DataFrame, bands: pd.DataFrame) -> str:
    """Both readings of R5, printed together, in the currency each was set in."""
    a = score_csv[score_csv["regime"] == "all"]
    out = ["\n=== R5 — does the covariate μ-model beat persistence? ===\n"]

    def cell(src: str, d: pd.DataFrame) -> dict:
        r = d[d["source"] == src]
        return {k: float(r[k].mean()) for k in
                ["pooled_r2", "rank_spearman", "sign_agree", "topdecile_hit"]}

    for label, d in [("ALL 46 WEEKS", a),
                     ("PRE-RTC+B", a[a["week"] < RTC_B]),
                     ("POST-RTC+B", a[a["week"] >= RTC_B])]:
        m, p = cell("model", d), cell("persistence", d)
        v = gate(m["pooled_r2"], m["rank_spearman"], m["sign_agree"],
                 m["topdecile_hit"])
        beat, detail = existence_test(m, p)
        out += [f"{label}  (n={d['week'].nunique()})",
                f"  gate            : {v}",
                f"    R² {m['pooled_r2']:+.3f} (bar 0.50 / 0.30)   "
                f"Spearman {m['rank_spearman']:.3f} (bar 0.70 / 0.60)   "
                f"sign {m['sign_agree']:.3f} (bar 0.85)   "
                f"top-dec {m['topdecile_hit']:.3f} (bar 0.60)",
                f"  existence test  : {'PASS' if beat else 'FAIL'} — {detail}",
                ""]

    if not bands.empty:
        out += ["=== BANDS (P10/P50/P90) ===",
                f"  weeks {len(bands)}   coverage80 {bands.coverage80.mean():.3f} "
                f"(target 0.800)   mean width ${bands.band_width.mean():.2f}",
                f"  P50: R² {bands.pooled_r2.mean():+.3f}   MAE "
                f"${bands.mae.mean():.2f}   pinball {bands.pinball.mean():.3f}",
                f"  SF coverage {bands.sf_coverage.mean():.3f} — μ-mass the map "
                f"has a column for; the rest is the map's blind spot, not the "
                f"forecast's miss", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    from compute.mu.mu_model import load_preds
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preds", default="/compute/mu/mu_preds.npz")
    p.add_argument("--scores", default="/compute/mu/mu_score_weekly.csv")
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None)
    p.add_argument("--nodal-out", default=None,
                   help="stream the per-week nodal P10/P50/P90 + point panel to "
                        "this flat vocab-coded .npz; omit and nothing changes "
                        "(no panel, metrics CSV byte-identical)")
    p.add_argument("--to-db", action="store_true",
                   help="COPY the --nodal-out panel into forecast_nodal and flip "
                        "the forecast_current[ercot] pointer (after rows land); "
                        "requires --nodal-out and --run-id")
    p.add_argument("--run-id", default=None,
                   help="model-version tag for the forecast_nodal rows + pointer "
                        "(e.g. mu-all-v1); required with --to-db / --load-nodal-npz")
    p.add_argument("--load-nodal-npz", default=None,
                   help="seed forecast_nodal from an EXISTING panel .npz and flip "
                        "the forecast_current[ercot] pointer, WITHOUT re-running the "
                        "walk — the npz-of-record bulk path for standing up a fresh "
                        "DB (e.g. production catch-up). Requires --run-id; skips "
                        "preds/M/C entirely")
    p.add_argument("--drivers", default=None,
                   help="offline/debug: materialize top-k driver rows for an "
                        "EXPLICIT comma-separated list of curated delivery days "
                        "(e.g. 2025-06-01,2025-07-15). Curated only — refuses a "
                        "span and >%d days (full history is ~75M rows)"
                        % DRIVERS_MAX_DAYS)
    p.add_argument("--drivers-out", default=None,
                   help="CSV path for --drivers rows (default: drivers_<k>.csv)")
    p.add_argument("--drivers-k", type=int, default=DRIVERS_K,
                   help="top-k constraints per (ts, sp) for --drivers")
    args = p.parse_args(argv)
    if args.to_db and not (args.nodal_out and args.run_id):
        p.error("--to-db requires --nodal-out (the panel is loaded from it) "
                "and --run-id")
    if args.load_nodal_npz:
        if not args.run_id:
            p.error("--load-nodal-npz requires --run-id (the run to seed + promote)")
        if args.nodal_out or args.to_db or args.drivers:
            p.error("--load-nodal-npz is a standalone seed-from-npz mode; it does "
                    "not run the walk, so --nodal-out/--to-db/--drivers make no "
                    "sense with it")
    curated = None
    if args.drivers is not None:
        try:
            curated = {d.date(): None for d in parse_curated_days(args.drivers)}
        except ValueError as e:
            p.error(str(e))

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    if args.load_nodal_npz:
        # Seed a fresh DB from the npz-of-record — no walk, no preds/M/C. The whole
        # run is (re)written and the pointer flipped LAST, one transaction, so a
        # reader never sees a half-loaded run (same discipline as --to-db).
        with psycopg.connect(dsn) as conn:
            n = nodal_to_db(args.load_nodal_npz, conn, run_id=args.run_id)
            upsert_pointer(conn, FORECAST_LAYER, args.run_id)
            conn.commit()
        log.info("forecast_nodal <- %s rows from %s (run_id=%s); "
                 "forecast_current[%s] -> %s", n, args.load_nodal_npz, args.run_id,
                 FORECAST_LAYER, args.run_id)
        return 0

    preds = load_preds(args.preds)
    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
    log.info("M = %s   C = %s", M.shape, C.shape)

    bands = walk(M, C, preds, args.draws, args.seed, nodal_out=args.nodal_out,
                 curated=curated)
    scores = pd.read_csv(args.scores, parse_dates=["week"])
    print(r5(scores, bands))
    if args.out and not bands.empty:
        bands.to_csv(args.out, index=False)
        print(f"wrote {args.out}")

    if curated is not None:
        # Curated-day debug: the walk filled `curated` with each requested day's
        # SF+μ artifact; materialize its top-k driver rows to CSV. If --run-id is
        # set, also land the artifact in forecast_sf_artifact (the object the
        # endpoints read; §4a) so a curated day is inspectable end to end.
        missing = [d for d, a in curated.items() if a is None]
        if missing:
            log.warning("--drivers: %d requested day(s) not covered by the walk "
                        "window — skipped: %s", len(missing), missing)
        conn = psycopg.connect(dsn) if args.run_id else None
        frames = []
        for day, art in curated.items():
            if art is None:
                continue
            frames.append(materialize_drivers(art, args.drivers_k).assign(
                delivery_date=day))
            if conn is not None:
                persist_sf_mu_artifact(conn, art.SF, art.E_mu,
                                       run_id=args.run_id, delivery_date=day)
        if conn is not None:
            conn.commit()
            conn.close()
        drivers = (pd.concat(frames, ignore_index=True) if frames
                   else pd.DataFrame())
        out = args.drivers_out or f"drivers_{args.drivers_k}.csv"
        drivers.to_csv(out, index=False)
        log.info("--drivers: %d rows across %d curated day(s) -> %s",
                 len(drivers), len(frames), out)

    if args.to_db:
        # Load the panel just written to disk, then flip the pointer LAST — one
        # transaction, so a reader never sees a half-written run.
        with psycopg.connect(dsn) as conn:
            n = nodal_to_db(args.nodal_out, conn, run_id=args.run_id)
            upsert_pointer(conn, FORECAST_LAYER, args.run_id)
            conn.commit()
        log.info("forecast_nodal <- %s rows (run_id=%s); forecast_current[%s] -> %s",
                 n, args.run_id, FORECAST_LAYER, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
