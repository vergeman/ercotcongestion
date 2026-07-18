"""SF projection — push the sampled μ heads through the map and read the bands.

This is the projection library extracted from the old `compute.mu.propagate`
(0095): the math that turns the two μ heads into a nodal distribution through the
shift-factor map, plus the on-disk panel/artifact encodings. It writes nothing to
a DB and owns no CLI — the runners in `compute/jobs/` (`backfill_nodal`,
`daily_forecast`) import it. The verdict/`walk`/DB-write orchestration lives in
`compute.jobs.backfill_nodal`.

The point forecast (commit 4) answers "how sure are you of the number" by turning
the two heads back into the distribution they were always implicitly describing:

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
market.

**The known understatement.** Head 1 is sampled independently per constraint. The
constraints are collinear (0083 — that is *why* R3 failed), so the true joint
binding set is far more correlated than independent Bernoullis, and a sum of
independent draws has too thin a tail. This makes coverage a *measurement*, not a
formality: if the bands are too narrow, this is the first place to look.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from compute.mu.score import LAM, MIN_HOURS, STD_FLOOR, WINDOW_DAYS, score_matrix
from compute.sf.fit import implied_shift_factors

log = logging.getLogger("compute.sf.project")

N_DRAWS = 200
DRAW_CHUNK = 25          # cap peak memory; percentiles need every draw kept
RESID_CAP = 500_000      # the pool is sampled from, not enumerated
QUANTILES = (10, 50, 90)

# The forecast reads the map's persisted weekly SF instead of refitting it daily
# (0095-0002). These pin the shared-fit contract:
MAP_RUN_ID = "map-v1"    # the served weekly SF-map run the forecast projects through
MAX_SF_AGE_DAYS = 14     # freshness floor: D − window_end must be ≤ this, else stale.
#   The map refits weekly (REFIT_DAYS), so the freshest complete window closes up to
#   ~a week before D even when current; 14d tolerates one fully missed weekly refresh
#   and fails loud beyond, rather than silently serving weeks-old geography.
MIN_SF_COVERAGE = 0.5    # min share of D's predicted binding MASS the map must locate


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


# --------------------------------------------------------------------------
# Persisted-SF read + guard (0095-0002) — the forecast projects μ through the
# weekly map's persisted SF instead of refitting SF on [D−240, D) every day.
# --------------------------------------------------------------------------

def resolve_sf_window(conn, run_id: str, *, as_of=None
                      ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Latest persisted ``(window_start, window_end)`` for ``run_id``, causal to
    ``as_of``.

    Returns the row with the greatest ``window_start`` whose fit closes at or before
    ``as_of`` (``window_end <= as_of``) — the freshest SF a forecast for ``as_of``
    may use without any interval ≥ ``as_of`` entering the fit (``window_end`` is the
    fit-window close, `rolling.py`). ``as_of=None`` drops the causality filter (the
    plain "newest window" the API serves). ``None`` if the run has no window.
    """
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute(
                "SELECT window_start, window_end FROM sf_window_meta "
                "WHERE run_id = %s ORDER BY window_start DESC LIMIT 1", (run_id,))
        else:
            cur.execute(
                "SELECT window_start, window_end FROM sf_window_meta "
                "WHERE run_id = %s AND window_end <= %s "
                "ORDER BY window_start DESC LIMIT 1",
                (run_id, pd.Timestamp(as_of)))
        row = cur.fetchone()
    if row is None:
        return None
    return pd.Timestamp(row[0]), pd.Timestamp(row[1])


def load_window_sf(conn, run_id: str, window_start) -> pd.DataFrame:
    """Read one persisted window's SF matrix (constraint_key × settlement_point).

    The map stores it threshold-sparsified (``|sf| < sf_threshold`` dropped), so an
    absent cell is a true zero: pivot and fill ``0.0`` to hand `draw_congestion` a
    dense matrix on the same axes a fresh fit would. Empty frame if the window has
    no rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
            "WHERE run_id = %s AND window_start = %s",
            (run_id, pd.Timestamp(window_start)))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["constraint_key", "settlement_point", "sf"])
    SF = df.pivot_table(index="constraint_key", columns="settlement_point",
                        values="sf", aggfunc="mean").fillna(0.0)
    SF.index.name = None
    SF.columns.name = None
    return SF


def sf_mass_coverage(SF: pd.DataFrame, wp: pd.DataFrame) -> float:
    """Share of D's predicted binding MASS (Σ ``p_bind·mu_gbm``) whose constraint
    the loaded map has a column for.

    Mass-weighted, not a raw key count: a covered key that never binds shouldn't
    prop up coverage, and a novel key that barely binds shouldn't sink it. ``1.0``
    when the day predicts no binding at all (nothing to locate — the degenerate-μ
    guard downstream handles a truly empty forecast)."""
    e_mu = wp["p_bind"].to_numpy(float) * wp["mu_gbm"].to_numpy(float)
    total = float(np.nansum(np.abs(e_mu)))
    if total <= 0:
        return 1.0
    covered = wp["key"].isin(set(SF.index)).to_numpy()
    return float(np.nansum(np.abs(e_mu[covered])) / total)


def load_forecast_sf(conn, D, wp: pd.DataFrame, *, run_id: str = MAP_RUN_ID,
                     max_age_days: int = MAX_SF_AGE_DAYS,
                     min_coverage: float = MIN_SF_COVERAGE) -> pd.DataFrame:
    """Load the weekly map's latest SF for delivery day ``D`` and guard it, or raise.

    Replaces the per-day ``[D−240, D)`` refit: the map already fits this SF weekly
    and persists it (`implied_shift_factors`, run ``run_id``); within the 7-day
    refit interval the model treats SF as stationary, so the freshest complete
    window is valid for ``D``. Causal by construction — only a window with
    ``window_end ≤ D`` is eligible, so the SF never saw an interval ≥ ``D``.

    Fails loud (the caller keeps the prior pointer) on any of: no window built for
    the run; stale (``D − window_end > max_age_days`` — a missed weekly refresh);
    an empty SF matrix; or coverage below ``min_coverage`` of D's predicted binding
    mass (the map universe and D's constraints have diverged).
    """
    D = pd.Timestamp(D)
    win = resolve_sf_window(conn, run_id, as_of=D)
    if win is None:
        raise RuntimeError(
            f"no persisted SF window for run_id={run_id!r} at/before {D.date()} — "
            f"the weekly map ({run_id}) has not been built. Refusing to forecast "
            f"without geography (keep prior pointer).")
    window_start, window_end = win
    age = (D - window_end).days
    if age > max_age_days:
        raise RuntimeError(
            f"stale SF map for {D.date()}: the latest {run_id} window closes "
            f"{window_end.date()} ({age}d old > {max_age_days}d floor). The weekly "
            f"refresh is behind — refusing to serve stale geography (keep pointer).")
    SF = load_window_sf(conn, run_id, window_start)
    if SF.empty:
        raise RuntimeError(
            f"empty SF matrix for {run_id} window {window_start.date()} — nothing "
            f"to project {D.date()} through (keep prior pointer).")
    cov = sf_mass_coverage(SF, wp)
    if cov < min_coverage:
        raise RuntimeError(
            f"low SF coverage for {D.date()}: the {run_id} map locates {cov:.1%} of "
            f"the day's predicted binding mass (< {min_coverage:.0%} floor). The map "
            f"universe and D's constraints have diverged — refusing (keep pointer).")
    log.info("SF from %s window %s (%dd old): %d constraints x %d SPs, coverage %.1f%%",
             run_id, window_start.date(), age, SF.shape[0], SF.shape[1], cov * 100)
    return SF


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    eps: np.ndarray, n_draws: int, rng: np.random.Generator,
    *, want_panel: bool = False, want_sf_mu: bool = False,
    forward_hours: pd.DatetimeIndex | None = None,
    sf: pd.DataFrame | None = None,
) -> tuple[dict | None, NodalPanel | None, pd.DataFrame | None, pd.DataFrame | None]:
    """One window, shared by the backtest and `forecast_day`.

    Score/draw over ``[s, end)`` and build the weekly-metrics row exactly as
    `walk()` did. The SF map comes from one of two places: fit on
    ``[s−WINDOW_DAYS, s)`` here (``sf=None``, the historic/self-contained path), or
    the persisted weekly map passed in via ``sf`` (0095-0002 — the forecast and the
    backfill both read the map's SF instead of refitting; `load_forecast_sf`
    resolves + guards it). Everything downstream of the SF matrix is identical
    either way.

    Returns ``(row, None, None, None)`` normally; with ``want_panel`` also the
    `NodalPanel` teed from the same draws and the same `np.percentile` call the
    metrics use; with ``want_sf_mu`` also the ``SF`` (K×N) actually used and
    ``E_mu`` (H×K on ``SF.index``) for the SF+μ artifact (§4a). ``(None, None,
    None, None)`` on any skip (empty fit window, empty SF, no scored hours) — the
    caller's `continue`.

    **Forward mode** (`forward_hours` given — `forecast_day` for a delivery day D
    with no realized congestion yet, §3.2): the scored hours are the caller's
    delivery-day calendar (D's 24 intervals) rather than ``M_score ∩ C_score``,
    no realized ``Y`` is read (``C`` is never indexed on the score side, so a
    ``C`` that is empty/absent for D cannot crash the panel), and ``row`` is
    ``None`` (no `band_metrics` without an outcome). The `want_panel`/`want_sf_mu`
    tees are byte-identical to the backtest.
    """
    forward = forward_hours is not None
    if sf is None:
        lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
        M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
        C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
        if M_fit.empty:
            return None, None, None, None
        SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                                   standardize=True, std_floor=STD_FLOOR)
    else:
        SF = sf                             # persisted weekly map (already guarded)
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
