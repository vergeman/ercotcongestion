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

import numpy as np
import pandas as pd

from compute.mu import availability, panel_engineering, panel_sources

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


# Compatibility exports preserve existing import paths while the implementations
# live at their dedicated seams.
ERCOT_TZ = availability.ERCOT_TZ
DAM_CLOSE_HOUR = availability.DAM_CLOSE_HOUR
dam_close = availability.dam_close
history_cutoff = availability.history_cutoff
delivery_day_of = availability.delivery_day_of
ct_day_bounds = availability.ct_day_bounds
_dam_close_expr = availability.dam_close_expr
_vintage_cutoff_expr = availability.vintage_cutoff_expr
load_forecast_panel = panel_sources.load_forecast_panel
wind_forecast_panel = panel_sources.wind_forecast_panel
solar_forecast_panel = panel_sources.solar_forecast_panel
outage_panel = panel_sources.outage_panel
calendar_features = panel_engineering.calendar_features


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


net_load_regime = panel_engineering.net_load_regime


def binding_history(M: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Build backward-only constraint-history features."""
    return panel_engineering.binding_history(
        M, days, BIND_DEADBAND, HISTORY_WINDOWS, LAG_WINDOWS)


candidate_keys = panel_engineering.candidate_keys
_downcast_join = panel_engineering.downcast_join
_attach_refit_features = panel_engineering.attach_refit_features


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


audit_leakage = panel_engineering.audit_leakage
