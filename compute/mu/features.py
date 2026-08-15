"""The covariate panel — everything the mu-model is allowed to know, and when.

plan/0085 commit 2.

**The prediction is made at DAM close.** For delivery day D, a bidder submits by
10:00 CT on D-1 and learns nothing more until the market clears. So the model's
question is: *standing at D-1 10:00, which constraints bind during day D, and how
hard?* Every feature here must be answerable from that vantage point.

**The one failure mode that matters.** A single lookahead feature manufactures
skill and invalidates the whole R5 gate. This project has already caught itself
once (0082's 0.986 R^2). The defence is not vigilance, it is an explicit
availability model — for every source, *when did this number become knowable?* —
plus `audit_leakage`, which re-derives that from the data itself and is asserted
in the tests.

**The availability model, and the one non-obvious entry in it.**

  ``load/wind/solar forecast``  vintaged: `posted_datetime` is the truth. Take the
      newest vintage with ``posted_datetime <= DAM close``. Migration 26 exists
      precisely because the old wind/solar tables had thrown this away.
  ``outages_zonal``             vintaged the same way.
  ``calendar``                  free.
  ``DAM shadow prices``         **the subtle one, and it cuts in our favour.**
      A day's DAM shadow prices are not realized during that day — they are
      *cleared* the day before, and ERCOT posts them ~13:30 CT on D-1. So
      standing at DAM close on D-1, the entire 24-hour shadow-price outcome of
      day **D-1** is already public (it was posted on D-2). Binding history may
      therefore run through the END of day D-1, not merely up to 10:00 that
      morning.

      Getting this wrong in the *cautious* direction (cutting history at the
      prediction instant) would throw away a full day of the freshest and most
      predictive history there is; getting it wrong in the other direction
      (letting day D's own prices in) is the 0.986 disaster. Hence
      `history_cutoff`, one function, tested from both sides.

      The exact posting hour does not matter, and that is worth stating: any
      value between 10:00 and midnight on D-1 yields the same cutoff, so the
      conclusion is not sensitive to the constant.

**Why `legacy/regimes/binners.py` is not imported**, though the plan names it:
two of its three drivers (`congestion_magnitude`, `binding_active`) are computed
from *realized* congestion, so they are lookaheads at DAM close by construction,
and `_qcut` fits its quantile edges over the entire array it is handed — a
lookahead even for the net-load driver. `net_load_regime` below re-derives the
one usable label with edges fitted on the trailing window only. `legacy/` stays
frozen.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

log = logging.getLogger("compute.mu.features")

ERCOT_TZ = "America/Chicago"

# ERCOT's Day-Ahead Market closes at 10:00 CT on the day before delivery.
DAM_CLOSE_HOUR = 10

# A constraint "binds" when its shadow price clears a deadband. 1.0 $/MWh matches
# legacy/regimes/binners.DEFAULT_BINDING_DEADBAND — a shared convention, not a
# tuned parameter.
BIND_DEADBAND = 1.0

# Trailing spans for the binding-history features, in days.
HISTORY_WINDOWS = (1, 7, 28)

# Trailing spans for the lagged-magnitude features (`lag_*`), in days. Short by
# design: these exist to carry *recent* magnitude, which is the content of
# persistence, and 28d of it is already covered by `mean_mu_28d`.
LAG_WINDOWS = (1, 7)


# --------------------------------------------------------------------------
# The availability model. Everything else in this file defers to these three.
# --------------------------------------------------------------------------

def dam_close(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """The instant the model must predict from, for a given delivery day (UTC).

    10:00 CT on D-1. Returned tz-aware in UTC so it can be compared directly
    against `posted_datetime` without any implicit-timezone guessing.
    """
    d = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    local = (d - pd.Timedelta(days=1)) + pd.Timedelta(hours=DAM_CLOSE_HOUR)
    return local.tz_localize(ERCOT_TZ).tz_convert("UTC")


def history_cutoff(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """Last shadow-price interval knowable at DAM close for `delivery_day` (UTC).

    Exclusive bound: use rows with ``interval_ts < history_cutoff(D)``.

    This is midnight CT on day D — i.e. **all of day D-1 is fair game**, because
    day D-1's DAM cleared and was published on D-2. See the module docstring; this
    is the single most easily-botched line in the package, in both directions.
    """
    d = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    return d.tz_localize(ERCOT_TZ).tz_convert("UTC")


def delivery_day_of(ts: pd.Timestamp | pd.DatetimeIndex):
    """The ERCOT-local delivery day an interval belongs to."""
    return pd.DatetimeIndex(pd.to_datetime(ts)).tz_convert(ERCOT_TZ).normalize().tz_localize(None)


def ct_day_bounds(delivery_day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The UTC `[start, end)` instants bounding one CT delivery day.

    DST-aware: `end - start` is 23h/24h/25h across a spring-forward/fall-back day.
    `DateOffset`, not `Timedelta`, crosses the boundary — pandas `Timedelta`
    arithmetic on a tz-aware `Timestamp` is absolute-time and ignores DST, so
    `start + pd.Timedelta(days=1)` lands an hour off on either transition day.

    A tz-naive `delivery_day` names the CT calendar date directly (the DB label);
    a tz-aware instant is first mapped to its own CT calendar date, so re-deriving
    bounds from an already-CT-midnight instant is a no-op — the property that lets
    every block-boundary caller in the pipeline share this one function.
    """
    ts = pd.Timestamp(delivery_day)
    start = (ts.tz_convert(ERCOT_TZ) if ts.tzinfo is not None
             else ts.tz_localize(ERCOT_TZ)).normalize()
    return start.tz_convert("UTC"), (start + pd.DateOffset(days=1)).tz_convert("UTC")


# --------------------------------------------------------------------------
# System covariates: the as-of vintaged reads
# --------------------------------------------------------------------------

# Each read takes the newest vintage published at or before that hour's DAM
# close. `DISTINCT ON` + `ORDER BY posted_datetime DESC` is what "newest
# admissible" means in SQL. The predicate is on `posted_datetime`, never on
# `interval_ts` — publication time is what a bidder is bounded by.
_DAM_CLOSE_SQL = """
    ((date_trunc('day', {ts} AT TIME ZONE '{tz}') - interval '1 day'
      + interval '{hour} hours') AT TIME ZONE '{tz}')
"""


def _dam_close_expr(ts_col: str) -> str:
    return _DAM_CLOSE_SQL.format(ts=ts_col, tz=ERCOT_TZ, hour=DAM_CLOSE_HOUR)


def _vintage_cutoff_expr(ts_col: str,
                         vintage_cutoff: pd.Timestamp | None) -> tuple[str, tuple]:
    """The vintage predicate's admissibility instant: DAM close, capped by
    `vintage_cutoff` (a run's fire instant) when one is given (0133).

    A live run's fire instant is always after DAM close, so the cap is a no-op
    for the final (h1) track and for ordinary live serving; a backfilled preview
    (h2) run passes its *historical* fire instant, which sits well before D's DAM
    close, so the cap genuinely restricts which vintage a backfilled preview can
    see — reproducing what the live h2 run actually could have known instead of
    reading the DAM-close-vintage default and silently re-labeling a final as a
    preview. `vintage_cutoff=None` (the default for every caller that has no
    notion of a fire instant, e.g. the backtest) returns the bare DAM-close
    expression with no bound parameter, so an uncapped caller's query text and
    plan are unchanged.
    """
    close = _dam_close_expr(ts_col)
    if vintage_cutoff is None:
        return close, ()
    return f"LEAST({close}, %s)", (pd.Timestamp(vintage_cutoff),)


def _read(conn, sql: str, params, index_col: str | None = None) -> pd.DataFrame:
    """Run a query straight off the psycopg cursor.

    `pd.read_sql` warns about non-SQLAlchemy connections on every call, and these
    run in the walk-forward loop — four warnings per week scored is noise that
    trains the reader to ignore warnings.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    return df.set_index(index_col) if index_col else df


def load_forecast_panel(conn, start, end,
                        vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """Zonal load forecast, at the vintage standing at DAM close (optionally capped
    earlier by `vintage_cutoff` — a backfilled preview's historical fire instant,
    0133)."""
    cutoff_expr, cutoff_params = _vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               coast, east, far_west, north, north_central,
               south_central, southern, west, system_total
          FROM load_forecast_zonal
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {cutoff_expr}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end) + cutoff_params, index_col="interval_ts")
    return df.add_prefix("load_").rename(
        columns={"load_posted_datetime": "vintage_load"})


def wind_forecast_panel(conn, start, end,
                        vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    cutoff_expr, cutoff_params = _vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               stwpf_system_wide, stwpf_panhandle, stwpf_coastal,
               stwpf_south, stwpf_west, stwpf_north,
               wgrpp_system_wide
          FROM wind_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {cutoff_expr}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end) + cutoff_params, index_col="interval_ts")
    return df.rename(columns={"posted_datetime": "vintage_wind"})


def solar_forecast_panel(conn, start, end,
                         vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    cutoff_expr, cutoff_params = _vintage_cutoff_expr("interval_ts", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               stppf_system_wide, stppf_centerwest, stppf_northwest,
               stppf_farwest, stppf_fareast, stppf_southeast, stppf_centereast,
               pvgrpp_system_wide
          FROM solar_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {cutoff_expr}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end) + cutoff_params, index_col="interval_ts")
    return df.rename(columns={"posted_datetime": "vintage_solar"})


def outage_panel(conn, start, end,
                 vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """Zonal outage MW at the DAM-close vintage (optionally capped earlier by
    `vintage_cutoff` — a backfilled preview's historical fire instant, 0133).

    This is the R4 fallback (plan/0085 commit 1): ERCOT publishes no
    transmission-outage feed reachable on our access path, so the outage covariate
    is a **load-zone aggregate — the same four numbers for every constraint**. It
    carries no per-constraint information and is expected to be a weak feature.
    Recorded here rather than dressed up.

    NP3-233 is forward-looking (the Outage Scheduler's next 168h, published
    hourly), so it is genuinely knowable at DAM close — the one thing that goes
    right about it.
    """
    cutoff_expr, cutoff_params = _vintage_cutoff_expr(
        "(operating_date::timestamp AT TIME ZONE '" + ERCOT_TZ + "')", vintage_cutoff)
    sql = f"""
        SELECT DISTINCT ON (operating_date, hour_ending)
               operating_date, hour_ending, posted_datetime,
               total_mw_south, total_mw_north, total_mw_west, total_mw_houston,
               irr_mw_south, irr_mw_north, irr_mw_west, irr_mw_houston
          FROM outages_zonal
         WHERE operating_date >= %s AND operating_date < %s
           AND posted_datetime <= {cutoff_expr}
         ORDER BY operating_date, hour_ending, posted_datetime DESC
    """
    df = _read(conn, sql, (pd.Timestamp(start).date(),
                          pd.Timestamp(end).date()) + cutoff_params)
    if df.empty:
        return pd.DataFrame()

    # hour_ending 1..24 -> the interval that ENDS at that hour, i.e. starts at h-1.
    local = (pd.to_datetime(df["operating_date"])
             + pd.to_timedelta(df["hour_ending"].astype(int) - 1, unit="h"))
    df["interval_ts"] = (local.dt.tz_localize(ERCOT_TZ, ambiguous=True,
                                              nonexistent="shift_forward")
                         .dt.tz_convert("UTC"))
    df = df.drop(columns=["operating_date", "hour_ending"]).set_index("interval_ts")

    # DST. `outages_zonal` carries no dst_flag and reports 24 hour-endings every
    # day, including the 23-hour spring-forward one — so its bogus 02:00 row gets
    # shifted onto 03:00 and collides with the real one. The other panels are
    # DISTINCT ON (interval_ts) and cannot collide; this one can, and an ordinary
    # concat then dies with "Reindexing only valid with uniquely valued Index".
    # Keep the last row: on the fall-back day that is the second (post-transition)
    # pass over the repeated hour, which is the one still in effect.
    return (df[~df.index.duplicated(keep="last")]
            .rename(columns={"posted_datetime": "vintage_outage"}))


def calendar_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Hour/day/month/weekend. Free of charge — a calendar leaks nothing."""
    local = pd.DatetimeIndex(idx).tz_convert(ERCOT_TZ)
    out = pd.DataFrame(index=idx)
    out["hour"] = local.hour
    out["dow"] = local.dayofweek
    out["month"] = local.month
    out["is_weekend"] = (local.dayofweek >= 5).astype(int)
    # Cyclical encodings: hour 23 and hour 0 are adjacent, and a tree has to burn
    # splits to learn that from a raw integer.
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    return out


def system_panel(conn, start, end,
                 vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """The hourly covariate frame: forecasts, net load, outages, calendar.

    Every column is knowable at DAM close, and every vintaged source keeps its
    `vintage_*` column so `audit_leakage` can prove it from the data rather than
    take this docstring's word for it. `vintage_cutoff`, when given, caps every
    read at that instant too (a backfilled preview's historical fire time, 0133).
    """
    parts = [load_forecast_panel(conn, start, end, vintage_cutoff),
             wind_forecast_panel(conn, start, end, vintage_cutoff),
             solar_forecast_panel(conn, start, end, vintage_cutoff),
             outage_panel(conn, start, end, vintage_cutoff)]
    panel = pd.concat([p for p in parts if not p.empty], axis=1).sort_index()

    # Net load — the physical driver of congestion, and the reason the wind/solar
    # backfill was worth doing: it is load minus what shows up for free.
    panel["net_load"] = (panel["load_system_total"]
                         - panel["stwpf_system_wide"]
                         - panel["stppf_system_wide"])

    # ERCOT's own published doubt. WGRPP/PVGRPP are the probable *lower* bounds
    # (the level generation is expected to exceed), so they sit BELOW the point
    # forecast — measured, not assumed: wgrpp - stwpf runs about -1.5 GW. Signing
    # it as (point - lower_bound) makes it a positive downside margin, which is
    # the natural covariate for a model whose own output is a P10/P50/P90: a wide
    # margin means the operator itself is unsure how much wind will show up.
    panel["wind_band"] = panel["stwpf_system_wide"] - panel["wgrpp_system_wide"]
    panel["solar_band"] = panel["stppf_system_wide"] - panel["pvgrpp_system_wide"]

    panel = panel.join(calendar_features(panel.index))
    return panel


def net_load_regime(panel: pd.DataFrame, fit_index: pd.DatetimeIndex,
                    n_buckets: int = 5) -> pd.Series:
    """Quantile-bucket net load, with the edges fitted on `fit_index` ONLY.

    The edges are the leak. `legacy/regimes/binners._qcut` derives cut points from
    the whole array it is given, so a bucket label computed over train+test
    encodes the test set's distribution — mild, but real, and free to avoid. Fit
    on the trailing training window; apply forward.
    """
    train = panel.loc[panel.index.isin(fit_index), "net_load"].dropna()
    if train.empty:
        return pd.Series(-1, index=panel.index, name="net_load_regime")

    edges = np.unique(np.quantile(train, np.linspace(0, 1, n_buckets + 1)[1:-1]))
    labels = np.digitize(panel["net_load"].to_numpy(), edges)
    out = pd.Series(labels, index=panel.index, name="net_load_regime")
    return out.where(panel["net_load"].notna(), -1)


# --------------------------------------------------------------------------
# Constraint covariates: backward-only binding history
# --------------------------------------------------------------------------

def binding_history(M: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Per (delivery_day, constraint): what its recent past looked like at DAM close.

    Returns a long frame indexed by (delivery_day, key). The features are
    constant within a delivery day by construction — which is exactly right, and
    is the whole content of `history_cutoff`: standing at DAM close, every hour of
    day D shares the same past. A feature that varied *within* day D could only do
    so by reading day D, which is the target.

    `M` is the shadow-price panel (hours x constraint key), as
    `compute.sf.panels.load_shadow_prices` returns it.

    **The `lag_*` columns are a defect fix, not a feature (plan/0088 commit 2).**
    Until 0088 this function emitted bind *incidence* recency (`binds_1d/7d/28d`,
    `days_since_bind`, `bind_rate_life`) plus a 28-day mean magnitude — and **no
    short-lag magnitude at all.** It could say *how often* a constraint bound
    lately and *how big it usually is over a month*, but not **how big it was
    yesterday**.

    That is a hole with a name: **persistence's entire content is yesterday's μ.**
    So the μ-model was not strictly more informed than the baseline it had to beat,
    and in 0085 it duly lost to it on top-decile (0.523 vs 0.561). The data was
    already in `M` the whole time. `lag_mu_1d/7d` and `lag_max_mu_1d/7d` close it.

    **No new cutoff is needed, and that is the one place the DAM's publication
    quirk works in our favour:** day D-1's shadow prices *cleared* on D-2 and are
    public well before the 10:00 DAM close on D-1. So `history_cutoff` already
    admits all 24 hours of D-1, and these features are legal by construction.
    """
    binds = (M.fillna(0.0).abs() > BIND_DEADBAND)
    mu = M.fillna(0.0).abs().where(binds, 0.0)

    # Daily aggregates first: rolling over ~570 days x keys is cheap, rolling over
    # ~14k hours x keys is not, and the day is the natural resolution here anyway.
    day_idx = delivery_day_of(M.index)
    daily_binds = binds.groupby(day_idx).sum()
    daily_mu = mu.groupby(day_idx).sum()
    daily_peak = mu.groupby(day_idx).max()
    # Hours actually present per day — NOT a hardcoded 24. DST days have 23 and 25,
    # and the panel's first and last days can be partial. Dividing a day's μ-sum by
    # 24 on a 23-hour day would quietly understate it.
    daily_hours = pd.Series(1, index=M.index).groupby(day_idx).sum()

    frames = []
    for d in days:
        cutoff = history_cutoff(d)
        # Strictly before the cutoff. `.loc[:cutoff]` would include it.
        past_days = daily_binds.index[daily_binds.index < cutoff.tz_convert(ERCOT_TZ)
                                      .tz_localize(None).normalize()]
        if len(past_days) == 0:
            continue
        b = daily_binds.loc[past_days]
        m = daily_mu.loc[past_days]
        pk = daily_peak.loc[past_days]
        nh = daily_hours.loc[past_days]

        row = {}
        for w in HISTORY_WINDOWS:
            recent = b.iloc[-w:] if w <= len(b) else b
            row[f"binds_{w}d"] = recent.sum()
        row["bind_rate_life"] = b.sum() / max(len(b) * 24, 1)
        row["mean_mu_28d"] = (m.iloc[-28:].sum()
                              / b.iloc[-28:].sum().replace(0, np.nan))

        # The lagged magnitudes. **Averaged over ALL hours in the window, not over
        # binding hours** — a slack hour's μ is a true, observed 0.0, not a missing
        # value, and that is not a technicality: it is the definition persistence
        # itself uses (`score.mu_persistence` reindexes to D-1 and fills 0.0). A
        # bind-conditional mean here would be a *different and much weaker*
        # quantity, undefined on exactly the quiet constraints whose quietness is
        # the most predictive thing about them. `mean_mu_28d` is already the
        # bind-conditional flavour; these are deliberately the other one.
        #
        # Hence no NaN and no fill: every value is a real observed average.
        for w in LAG_WINDOWS:
            row[f"lag_mu_{w}d"] = m.iloc[-w:].sum() / max(int(nh.iloc[-w:].sum()), 1)
            # The peak, kept separately, because the mean and the tail are
            # different signals and 0086 is the proof: the model that knows a
            # constraint's *average* still cannot tell which ones spike. A daily
            # mean of $4 is a constraint that bound gently all day OR one that hit
            # $96 for an hour, and only the second is a top-decile event.
            row[f"lag_max_mu_{w}d"] = pk.iloc[-w:].max()

        # Days since the constraint last bound. A never-binder gets the full span,
        # which is the honest encoding of "no evidence it ever binds".
        ever = b.loc[:, b.sum() > 0]
        last = pd.Series(len(b), index=b.columns, dtype=float)
        if not ever.empty:
            pos = ever.apply(lambda c: np.flatnonzero(c.to_numpy() > 0)[-1])
            last.loc[ever.columns] = len(b) - 1 - pos
        row["days_since_bind"] = last

        f = pd.DataFrame(row)
        f["delivery_day"] = d
        f.index.name = "key"
        frames.append(f.reset_index())

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.set_index(["delivery_day", "key"]).fillna(0.0)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def candidate_keys(hist: pd.DataFrame, policy: str = "active_28d") -> pd.DataFrame:
    """Which constraints the model is asked about on a given day.

    This is a **modelling choice with teeth**, not plumbing, so it is a named
    policy rather than a filter buried in a join:

      ``all``        every constraint with any history. Honest, and enormous:
                     ~2,200 keys x 24h x ~570d. Most rows are a constraint that
                     has not bound in a year being asked, again, whether it will
                     bind — which drives the positive rate toward zero and makes
                     calibration the only metric that still means anything.
      ``active_28d`` (default) constraints that bound at least once in the
                     trailing 28 days. This is also a screening product, so the
                     base rate the model is calibrated against is the base rate
                     it is used at.

    The choice moves the positive rate and therefore every headline number, so
    commit 4 must report which policy produced a score. It is never a free
    simplification.
    """
    if policy == "all":
        return hist
    if policy == "active_28d":
        return hist[hist["binds_28d"] > 0]
    raise ValueError(f"unknown candidate policy: {policy!r}")


def _downcast_join(df: pd.DataFrame) -> pd.DataFrame:
    """float64 → float32 on a frame about to be merged into the panel.

    float32 is the panel's *final* storage dtype anyway (see the terminal cast in
    `build_panel`): the covariates are MW and $/MWh at 4-5 significant figures, so
    float64 stores precision the source data does not have. Doing it here, on each
    component **before** it is joined, is what keeps the assembled panel from ever
    going float64-wide — the state whose end-of-build cast to float32 doubled the
    panel and OOM-killed the ablation. Result-identical to casting at the end,
    because the walk always saw the float32 panel; only the peak changes.

    Only applied to frames being merged in, never to a frame something is still
    computed from (e.g. the float64 `sys_panel` `wx_panel` reads) — downcasting
    those would change a covariate rather than just its storage.
    """
    f64 = df.select_dtypes("float64").columns
    if len(f64):
        df[f64] = df[f64].astype("float32")
    return df


def _attach_refit_features(panel: pd.DataFrame, days: pd.DatetimeIndex,
                           values: pd.DataFrame) -> None:
    """Attach one refit's per-key values directly to the panel's week rows.

    ``geo_panel`` and ``wx_panel`` produce one vector per constraint for a refit
    week.  Materialising that vector once per delivery day and then merging it
    copies the already-wide panel at its largest point.  The values are constant
    within the refit week, so align them to the panel's existing key rows instead.

    This mutates ``panel`` in place.  Missing keys remain NaN, exactly as the old
    left merge did; numeric values become float32 by the same boundary rule as
    ``_downcast_join``.
    """
    if values.empty or not len(days):
        return
    if not values.index.is_unique:
        raise ValueError("refit feature values must have one row per key")

    positions = np.flatnonzero(panel["delivery_day"].isin(days).to_numpy())
    if not len(positions):
        return
    aligned = values.reindex(panel.iloc[positions]["key"])
    for col in aligned.columns:
        if col not in panel:
            panel[col] = np.full(len(panel), np.nan, dtype=np.float32)
        panel.iloc[positions, panel.columns.get_loc(col)] = aligned[col].to_numpy(
            dtype=np.float32, na_value=np.nan
        )


def build_panel(conn, M: pd.DataFrame, start, end,
                policy: str = "active_28d",
                C: pd.DataFrame | None = None,
                score_from: pd.Timestamp | None = None,
                with_weather: bool = False,
                with_outage: bool = False,
                vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """The design matrix: one row per (delivery hour, candidate constraint).

    Columns are the system covariates (same for every constraint in an hour) plus
    that constraint's own history (same for every hour in a day) plus the targets.
    Both targets are carried, because the two heads want different things:

        ``y_bind``  did it bind this hour (0/1)          -> head 1
        ``y_mu``    the shadow price, given it bound     -> head 2 (NaN if it did not)

    The targets come from `M` and are the ONLY place day D's own data appears. No
    feature column may be derived from them.

    **Missing covariates stay NaN. Do not fill them.** Over 2024-12-11..2026-07-01
    the panel has exactly two pockets of missingness, and both are meaningful:

      * outage columns are absent before **2024-12-31** — `outages_zonal` ingest
        simply starts there (529 hours, all of them before the first scored week,
        so they touch only the earliest training margin);
      * solar is absent for **2 hours ever**, 2025-03-09 07:00 and 2026-03-08
        07:00 UTC — the DST spring-forward hour, which does not exist locally.
        Wind publishes a row for it, solar does not.

    Filling either with a zero or a neighbour would invent a covariate value the
    market never saw, which is the same class of error as a lookahead: it makes
    the model look better than the information available to it. The gradient
    boosters in commit 3 take NaN natively; let them see the hole.

    **The 0088 arms are opt-in, and both default to off**, so a caller that asks
    for nothing gets exactly 0085's panel — which is what keeps every existing
    test honest:

      ``C``             turns on the **geography** arm (commit 3). The `geo_*`
                        columns need the congestion panel because they come from
                        `SF`, which is *fitted* from `M` and `C` together.
      ``with_weather``  turns on the **weather-response** arm (commit 4). It needs
                        no extra data at all — only `M` and the forecasts already
                        in `sys_panel`.
      ``with_outage``   turns on the **generation-outage** arm (plan/0089). Like
                        `C`, it is |SF|-based, so it needs the congestion panel and
                        raises without it; it also reads `resource_outages` and the
                        authoritative crosswalk to place units onto settlement points.
      ``score_from``    phase-locks both arms' refit grids to the scoring harness's.
                        It selects nothing and gates nothing.
      ``vintage_cutoff`` caps every vintaged read at this instant too (0133): a
                        backfilled preview (h2) run passes its historical fire
                        time so a re-backfilled day sees only what the live h2
                        run actually could have, instead of the DAM-close-vintage
                        default silently re-labeling a final as a preview. `None`
                        (the default — live serving, h1, and the backtest) is a
                        no-op that leaves the DAM-close cutoff alone.

    The ablation (commit 5) builds this **once** with every arm on, then selects
    arms by column-name prefix. These flags exist so a single-arm run can skip work
    it does not need, never so that an arm can be measured on a different panel.
    """
    sys_panel = system_panel(conn, start, end, vintage_cutoff)
    if sys_panel.empty:
        return pd.DataFrame()

    hours = sys_panel.index
    days = pd.DatetimeIndex(np.unique(delivery_day_of(hours)))
    hist = candidate_keys(binding_history(M, days), policy)
    if hist.empty:
        return pd.DataFrame()

    # Cross the day's candidates with the day's hours. Each component is downcast to
    # float32 *before* it is merged (`_downcast_join`) so the wide panel is never
    # materialised in float64 — see that helper for why this is result-identical and
    # why it matters for peak memory.
    frame = pd.DataFrame({"interval_ts": hours,
                          "delivery_day": delivery_day_of(hours)})
    panel = frame.merge(_downcast_join(hist.reset_index()), on="delivery_day",
                        how="inner")

    panel = panel.merge(
        _downcast_join(sys_panel.drop(columns=[c for c in sys_panel.columns
                                               if c.startswith("vintage_")])),
        left_on="interval_ts", right_index=True, how="left")

    # Geography: per (delivery_day, key), from the honestly-refit SF. A LEFT join,
    # so a constraint the week's SF could not locate keeps its hole rather than
    # borrowing another constraint's position.
    if C is not None and not C.empty:
        from compute.mu.geo import geo_panel
        geo_panel(
            M, C, days, anchor=score_from,
            on_refit=lambda week_days, values: _attach_refit_features(
                panel, week_days, values),
        )

    # Weather-response vectors: per (delivery_day, key), correlations over the same
    # trailing window. Needs no `C` and no crosswalk — only M and the forecasts that
    # are already in `sys_panel`. Same LEFT join, same law about holes.
    #
    # `wx_panel` is handed the float64 `sys_panel` (NOT a downcast copy): it computes
    # weather-response correlations from those columns, so downcasting them first
    # would change the covariate, not just its storage. Only the join copy is slimmed.
    if with_weather:
        from compute.mu.weather import wx_panel
        wx_panel(
            M, sys_panel, days, anchor=score_from,
            on_refit=lambda week_days, values: _attach_refit_features(
                panel, week_days, values),
        )

    # Generation-outage exposure (plan/0089): per (delivery_day, key), |SF| dotted
    # against the located outage MW of the D-4 vintage. Same construction as `geo`
    # — it fits its own honestly-refit SF from M and C — so it needs `C` (the SF's
    # settlement-point space) and the authoritative crosswalk to place units there.
    # Same LEFT join, same law about holes: a day whose vintage/SF cannot place a
    # constraint keeps its NaN rather than borrowing a zero.
    if with_outage:
        if C is None or C.empty:
            raise ValueError("with_outage needs the congestion panel C — the outage "
                             "exposure is |SF|·MW and the SF is fitted from M and C")
        from compute.mu.outage_crosswalk import load_crosswalk
        from compute.mu.outage_exposure import (load_located_outages,
                                                outage_exposure_panel)
        outages = load_located_outages(conn, load_crosswalk(), set(C.columns),
                                       pd.Timestamp(start).date(),
                                       pd.Timestamp(end).date())
        out = outage_exposure_panel(M, C, outages, days, anchor=score_from)
        if not out.empty:
            panel = panel.merge(_downcast_join(out.reset_index()),
                                on=["delivery_day", "key"], how="left")
            del out

    # The target read: |μ| at each (hour, key) the panel asks about. The obvious
    # `M.reindex(cols=used).stack()` materialises a ~30M-row MultiIndexed Series to
    # read back ~10M values — historically the peak-memory line of the package. A
    # dense gather does the same lookup without ever building that index: reindex M
    # to the candidate columns once (a 13.6k × ~2.2k matrix), then fancy-index it by
    # the panel's (hour, key) integer positions. Every panel key is in `used` and
    # every panel hour is in `hours`, so no position is missing; NaN (M had no cell)
    # becomes 0.0, exactly as `.fillna(0.0)` did.
    used = pd.Index(panel["key"].unique())
    mu = M.reindex(index=hours, columns=used).abs().to_numpy()
    ri = hours.get_indexer(pd.DatetimeIndex(panel["interval_ts"]))
    ci = used.get_indexer(panel["key"])
    y = mu[ri, ci]
    del mu
    y[np.isnan(y)] = 0.0

    panel["y_mu"] = y
    panel["y_bind"] = (panel["y_mu"] > BIND_DEADBAND).astype("int8")
    panel.loc[panel["y_bind"] == 0, "y_mu"] = np.nan

    # Belt-and-braces: every covariate was downcast before its merge, so this should
    # find nothing but `y_mu` (kept float64 as the NaN-bearing target). Left in as a
    # cheap invariant — if a float64 covariate ever sneaks through, it is caught here
    # rather than silently doubling the panel again.
    floats = panel.select_dtypes("float64").columns.drop("y_mu", errors="ignore")
    if len(floats):
        panel[floats] = panel[floats].astype("float32")

    return panel.set_index(["interval_ts", "key"]).sort_index()


# --------------------------------------------------------------------------
# The leak audit — the acceptance criterion, expressed as code
# --------------------------------------------------------------------------

def audit_leakage(panel: pd.DataFrame) -> pd.DataFrame:
    """Prove, from the data, that no row read anything published after DAM close.

    For each vintaged source, compare the vintage actually used against the DAM
    close of the hour it describes. `slack_h` is hours of margin; **any negative
    value is a leak** and the tests assert there are none.

    This is deliberately a data-level check, not a static one. A reviewer can
    convince themselves a SQL predicate is right and still be wrong about what the
    table contains — 0.0% of the old wind/solar rows were DAM-close-admissible,
    and nothing in the code said so.
    """
    rows = []
    for col in [c for c in panel.columns if c.startswith("vintage_")]:
        used = pd.to_datetime(panel[col]).dropna()
        if used.empty:
            continue
        # Go through DatetimeIndex, never `.values` — the numpy round-trip drops
        # the timezone, and a naive-vs-aware comparison here is exactly the kind
        # of silent hour-shift this function exists to catch.
        published = pd.DatetimeIndex(used)
        if published.tz is None:
            published = published.tz_localize("UTC")
        closes = pd.DatetimeIndex([dam_close(d) for d in
                                   delivery_day_of(used.index)])
        slack_h = (closes - published) / pd.Timedelta(hours=1)
        rows.append({
            "source": col.removeprefix("vintage_"),
            "n_rows": len(used),
            "min_slack_h": float(np.min(slack_h)),
            "median_slack_h": float(np.median(slack_h)),
            "n_leaks": int((slack_h < 0).sum()),
        })
    return pd.DataFrame(rows)
