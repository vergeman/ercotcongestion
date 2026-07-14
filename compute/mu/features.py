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


def load_forecast_panel(conn, start, end) -> pd.DataFrame:
    """Zonal load forecast, at the vintage standing at DAM close."""
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               coast, east, far_west, north, north_central,
               south_central, southern, west, system_total
          FROM load_forecast_zonal
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {_dam_close_expr('interval_ts')}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end), index_col="interval_ts")
    return df.add_prefix("load_").rename(
        columns={"load_posted_datetime": "vintage_load"})


def wind_forecast_panel(conn, start, end) -> pd.DataFrame:
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               stwpf_system_wide, stwpf_panhandle, stwpf_coastal,
               stwpf_south, stwpf_west, stwpf_north,
               wgrpp_system_wide
          FROM wind_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {_dam_close_expr('interval_ts')}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end), index_col="interval_ts")
    return df.rename(columns={"posted_datetime": "vintage_wind"})


def solar_forecast_panel(conn, start, end) -> pd.DataFrame:
    sql = f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, posted_datetime,
               stppf_system_wide, stppf_centerwest, stppf_northwest,
               stppf_farwest, stppf_fareast, stppf_southeast, stppf_centereast,
               pvgrpp_system_wide
          FROM solar_forecast_regional
         WHERE interval_ts >= %s AND interval_ts < %s
           AND posted_datetime <= {_dam_close_expr('interval_ts')}
         ORDER BY interval_ts, posted_datetime DESC
    """
    df = _read(conn, sql, (start, end), index_col="interval_ts")
    return df.rename(columns={"posted_datetime": "vintage_solar"})


def outage_panel(conn, start, end) -> pd.DataFrame:
    """Zonal outage MW at the DAM-close vintage.

    This is the R4 fallback (plan/0085 commit 1): ERCOT publishes no
    transmission-outage feed reachable on our access path, so the outage covariate
    is a **load-zone aggregate — the same four numbers for every constraint**. It
    carries no per-constraint information and is expected to be a weak feature.
    Recorded here rather than dressed up.

    NP3-233 is forward-looking (the Outage Scheduler's next 168h, published
    hourly), so it is genuinely knowable at DAM close — the one thing that goes
    right about it.
    """
    sql = f"""
        SELECT DISTINCT ON (operating_date, hour_ending)
               operating_date, hour_ending, posted_datetime,
               total_mw_south, total_mw_north, total_mw_west, total_mw_houston,
               irr_mw_south, irr_mw_north, irr_mw_west, irr_mw_houston
          FROM outages_zonal
         WHERE operating_date >= %s AND operating_date < %s
           AND posted_datetime <= {_dam_close_expr(
               "(operating_date::timestamp AT TIME ZONE '" + ERCOT_TZ + "')")}
         ORDER BY operating_date, hour_ending, posted_datetime DESC
    """
    df = _read(conn, sql, (pd.Timestamp(start).date(),
                          pd.Timestamp(end).date()))
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


def system_panel(conn, start, end) -> pd.DataFrame:
    """The hourly covariate frame: forecasts, net load, outages, calendar.

    Every column is knowable at DAM close, and every vintaged source keeps its
    `vintage_*` column so `audit_leakage` can prove it from the data rather than
    take this docstring's word for it.
    """
    parts = [load_forecast_panel(conn, start, end),
             wind_forecast_panel(conn, start, end),
             solar_forecast_panel(conn, start, end),
             outage_panel(conn, start, end)]
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
    """
    binds = (M.fillna(0.0).abs() > BIND_DEADBAND)
    mu = M.fillna(0.0).abs().where(binds, 0.0)

    # Daily aggregates first: rolling over ~570 days x keys is cheap, rolling over
    # ~14k hours x keys is not, and the day is the natural resolution here anyway.
    day_idx = delivery_day_of(M.index)
    daily_binds = binds.groupby(day_idx).sum()
    daily_mu = mu.groupby(day_idx).sum()

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

        row = {}
        for w in HISTORY_WINDOWS:
            recent = b.iloc[-w:] if w <= len(b) else b
            row[f"binds_{w}d"] = recent.sum()
        row["bind_rate_life"] = b.sum() / max(len(b) * 24, 1)
        row["mean_mu_28d"] = (m.iloc[-28:].sum()
                              / b.iloc[-28:].sum().replace(0, np.nan))

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
                     trailing 28 days. This is also what a screening product would
                     actually put in front of a trader, so the base rate the model
                     is calibrated against is the base rate it is used at.

    The choice moves the positive rate and therefore every headline number, so
    commit 4 must report which policy produced a score. It is never a free
    simplification.
    """
    if policy == "all":
        return hist
    if policy == "active_28d":
        return hist[hist["binds_28d"] > 0]
    raise ValueError(f"unknown candidate policy: {policy!r}")


def build_panel(conn, M: pd.DataFrame, start, end,
                policy: str = "active_28d") -> pd.DataFrame:
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
    """
    sys_panel = system_panel(conn, start, end)
    if sys_panel.empty:
        return pd.DataFrame()

    hours = sys_panel.index
    days = pd.DatetimeIndex(np.unique(delivery_day_of(hours)))
    hist = candidate_keys(binding_history(M, days), policy)
    if hist.empty:
        return pd.DataFrame()

    # Cross the day's candidates with the day's hours.
    frame = pd.DataFrame({"interval_ts": hours,
                          "delivery_day": delivery_day_of(hours)})
    panel = frame.merge(hist.reset_index(), on="delivery_day", how="inner")

    panel = panel.merge(sys_panel.drop(columns=[c for c in sys_panel.columns
                                                if c.startswith("vintage_")]),
                        left_on="interval_ts", right_index=True, how="left")

    # Stack only the keys that are actually candidates. Stacking all of `M`
    # (13.6k hours x ~2.2k keys) materialises ~30M cells to read back ~10M, and
    # this is the peak-memory line of the whole package.
    used = panel["key"].unique()
    mu = M.reindex(index=hours, columns=used).fillna(0.0).abs()
    lookup = mu.stack()
    lookup.index.names = ["interval_ts", "key"]
    y = lookup.reindex(pd.MultiIndex.from_frame(panel[["interval_ts", "key"]]))

    panel["y_mu"] = y.to_numpy()
    panel["y_bind"] = (panel["y_mu"] > BIND_DEADBAND).astype("int8")
    panel.loc[panel["y_bind"] == 0, "y_mu"] = np.nan

    # float32 halves the panel (~10M rows x ~50 cols). The covariates are MW and
    # $/MWh at 4-5 significant figures; float64 stores precision that does not
    # exist in the source data.
    floats = panel.select_dtypes("float64").columns.drop("y_mu", errors="ignore")
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
