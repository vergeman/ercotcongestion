"""The covariate panel — everything the mu-model is allowed to know, and when.

**The prediction is made at DAM close.** For delivery day D, a bidder submits by
10:00 CT on D-1 and learns nothing more until the market clears. So the model's
question is: *standing at D-1 10:00, which constraints bind during day D, and how
hard?* Every feature here must be answerable from that vantage point.

**The availability model**

  ``load/wind/solar forecast``  vintaged: `posted_datetime` is the truth. Take the
      newest vintage with ``posted_datetime <= DAM close``.
  ``outages_zonal``             vintaged the same way.
  ``calendar``                  free.
  ``DAM shadow prices``
      A day's DAM shadow prices are not realized during that day — they are
      *cleared* the day before, and ERCOT posts them ~13:30 CT on D-1. So
      standing at DAM close on D-1, the entire 24-hour shadow-price outcome of
      day **D-1** is already public (it was posted on D-2). Binding history may
      therefore run through the END of day D-1, not merely up to 10:00 that
      morning.

      The exact posting hour does not matter, and that is worth stating: any
      value between 10:00 and midnight on D-1 yields the same cutoff, so the
      conclusion is not sensitive to the constant.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from compute.time import delivery_day_of

from compute.mu_forecast.panel import (
    availability,
    engineering as panel_engineering,
    sources as panel_sources,
)

log = logging.getLogger("compute.mu_forecast.panel.build")

# A constraint "binds" when its shadow price clears a deadband. 1.0 $/MWh matches
# legacy/regimes/binners.DEFAULT_BINDING_DEADBAND
BIND_DEADBAND = 1.0

# Trailing spans for the binding-history features, in days.
HISTORY_WINDOWS = (1, 7, 28)

# Trailing spans for the lagged-magnitude features (`lag_*`), in days. Short by
# design: these exist to carry *recent* magnitude, which is the content of
# persistence, and 28d of it is already covered by `mean_mu_28d`.
LAG_WINDOWS = (1, 7)


def binding_history(M: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Build backward-only constraint-history features."""
    return panel_engineering.binding_history(
        M, days, BIND_DEADBAND, HISTORY_WINDOWS, LAG_WINDOWS)


def system_panel(conn, start, end,
                 vintage_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """The hourly covariate frame: forecasts, net load, outages, calendar.

    Every column is knowable at DAM close, and every vintaged source keeps its
    `vintage_*` column so `audit_leakage` can prove it from the data.
    `vintage_cutoff`, when given, caps every read at that instant too (a
    backfilled preview's historical fire time).

    """
    # panel_sources are all sql queries
    parts = [panel_sources.load_forecast_panel(conn, start, end, vintage_cutoff),
             panel_sources.wind_forecast_panel(conn, start, end, vintage_cutoff),
             panel_sources.solar_forecast_panel(conn, start, end, vintage_cutoff),
             panel_sources.outage_panel(conn, start, end, vintage_cutoff)]
    panel = pd.concat([p for p in parts if not p.empty], axis=1).sort_index()

    # Net load — the physical driver of congestion, and the reason the wind/solar
    # backfill was worth doing: it is load minus what shows up for free.
    panel["net_load"] = (panel["load_system_total"]
                         - panel["stwpf_system_wide"]
                         - panel["stppf_system_wide"])

    # ERCOT's own published doubt. WGRPP/PVGRPP are the probable *lower* bounds
    # (the level generation is expected to exceed), so they sit BELOW the point
    # forecast — measured, not assumed: wgrpp - stwpf runs about -1.5 GW.
    # Signing it as (point - lower_bound) makes it a positive downside margin:
    # a wide margin means the operator itself is unsure how much wind will show
    # up.
    #
    # WGRPP: Wind-powered Generation Resource Production Potential
    # STWPF: Short-Term Wind Power Forecast
    # STPPF: Short-Term PV Power Forecast
    # PVGRPP: PhotoVoltaic Generation Resource Production Potential
    panel["wind_band"] = panel["stwpf_system_wide"] - panel["wgrpp_system_wide"]
    panel["solar_band"] = panel["stppf_system_wide"] - panel["pvgrpp_system_wide"]

    panel = panel.join(panel_engineering.calendar_features(panel.index))
    return panel


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

      * arms (features):

      ``C`` turns on the **geography** arm. The `geo_*` columns need the
      congestion panel because they come from `SF`, which is *fitted* from `M`
      and `C` together.

      ``with_weather`` turns on the **weather-response** arm. It needs no extra
      data at all — only `M` and the forecasts already in `sys_panel`.

      ``with_outage`` turns on the **generation-outage** arm. Like `C`, it is
      |SF|-based, so it needs the congestion panel it also reads
      `resource_outages` and the authoritative crosswalk to place units onto
      settlement points.

      ``score_from``    phase-locks both arms' refit grids to the scoring harness's.

      ``vintage_cutoff`` caps every vintaged read at this instant: a backfilled
      preview (h2) run passes its historical fire time so a re-backfilled day
      sees only what the live h2 run actually could have, `None`(the default —
      live serving, h1, and the backtest) is a no-op that leaves the DAM-close
      cutoff alone.

    The ablation builds this **once** with every arm on, then selects arms by
    column-name prefix. These flags exist so a single-arm run can skip work it
    does not need, never so that an arm can be measured on a different panel.

    """
    # covariate panels
    sys_panel = system_panel(conn, start, end, vintage_cutoff)
    if sys_panel.empty:
        return pd.DataFrame()

    # (date (day), constraint) binding history columns
    # NB: delivery_day_of is a single CT delivery day (00:00:00)
    hours = sys_panel.index
    days = pd.DatetimeIndex(np.unique(delivery_day_of(hours)))
    hist = panel_engineering.candidate_keys(binding_history(M, days), policy)
    if hist.empty:
        return pd.DataFrame()

    # Cross the day's candidates with the day's hours. Each component is downcast to
    # float32 *before* it is merged (`_downcast_join`) so the wide panel is never
    # materialised in float64 — see that helper for why this is result-identical and
    # why it matters for peak memory.
    frame = pd.DataFrame({"interval_ts": hours,
                          "delivery_day": delivery_day_of(hours)})
    panel = frame.merge(panel_engineering.downcast_join(hist.reset_index()),
                        on="delivery_day",
                        how="inner")

    panel = panel.merge(
        panel_engineering.downcast_join(
            sys_panel.drop(columns=[c for c in sys_panel.columns
                                    if c.startswith("vintage_")])),
        left_on="interval_ts", right_index=True, how="left")

    # --- at this point, our panel has
    # 1. from frame: interval_ts, (UTC timestamp) and ERCOT CT delivery_day
    # 2. from hist, joined on delivery_day: the constraint and its bind, lag
    # histories - "backward stats"
    # 3. from sys_panel, joined by interval_ts: covariates - our inputs;
    # forecasts, outages, net_loads, etc.
    # ---

    def attach_refit_features(week_days: pd.DatetimeIndex, values: pd.DataFrame) -> None:
        panel_engineering.attach_refit_features(panel, week_days, values)

    # Geography: per (delivery_day, key), we extract weight avg geolocation
    # from the SF: a LEFT join, so a constraint the week's SF could not locate
    # keeps its hole rather than borrowing another constraint's position.
    if C is not None and not C.empty:
        from compute.sf_map.geography.derive import geo_panel

        geo_panel(
            M, C, days,
            anchor=score_from,
            on_refit=attach_refit_features,
        )

    # Weather-response vectors: per (delivery_day, key), correlations over the same
    # trailing window. Needs no `C` and no crosswalk — only M and the forecasts that
    # are already in `sys_panel`. Same LEFT join, same law about holes.
    #
    # `wx_panel` is handed the float64 `sys_panel` (NOT a downcast copy): it computes
    # weather-response correlations from those columns, so downcasting them first
    # would change the covariate, not just its storage. Only the join copy is slimmed.
    if with_weather:
        from compute.mu_forecast.covariates.weather import wx_panel

        wx_panel(
            M, sys_panel, days,
            anchor=score_from,
            on_refit=attach_refit_features,
        )

    # Generation-outage exposure: per (delivery_day, key), |SF| against the
    # located outage MW. Same construction as `geo`.
    #
    # for default 'all' - with_outage is typically skipped.
    #
    # plan/0089-generation-outage-arm.md: ablation indicated the effect of
    # outage information was negligible.
    #
    if with_outage:
        if C is None or C.empty:
            raise ValueError("with_outage needs the congestion panel C — the outage "
                             "exposure is |SF|·MW and the SF is fitted from M and C")
        from compute.mu_forecast.covariates.outages.crosswalk import load_crosswalk
        from compute.mu_forecast.covariates.outages.exposure import (load_located_outages,
                                                outage_exposure_panel)

        outages = load_located_outages(conn, load_crosswalk(), set(C.columns),
                                       pd.Timestamp(start).date(),
                                       pd.Timestamp(end).date())
        out = outage_exposure_panel(M, C, outages, days, anchor=score_from)
        if not out.empty:
            panel = panel.merge(panel_engineering.downcast_join(out.reset_index()),
                                on=["delivery_day", "key"], how="left")
            del out

    # The target read: |μ| at each (hour, key)
    # y collapses from two dimensions to one because each panel row specifies
    # exactly one cell: one hour and one constraint.

    used = pd.Index(panel["key"].unique())                          # constraints
    mu = M.reindex(index=hours, columns=used).abs().to_numpy()      # hourly matrix for mu (abs)
    ri = hours.get_indexer(pd.DatetimeIndex(panel["interval_ts"]))  # row index: hour
    ci = used.get_indexer(panel["key"])                             # column index: constraint
    y = mu[ri, ci]                                                  # target (rows and cols)
    del mu
    y[np.isnan(y)] = 0.0

    panel["y_mu"] = y
    panel["y_bind"] = (panel["y_mu"] > BIND_DEADBAND).astype("int8")
    panel.loc[panel["y_bind"] == 0, "y_mu"] = np.nan

    # Downcast
    floats = panel.select_dtypes("float64").columns.drop("y_mu", errors="ignore")
    if len(floats):
        panel[floats] = panel[floats].astype("float32")

    return panel.set_index(["interval_ts", "key"]).sort_index()
