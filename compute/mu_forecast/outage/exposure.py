"""Per-constraint outage exposure, via the |SF| crosswalk. plan/0089 commit 3.

**The covariate R4 wanted and could not build.** `features.outage_panel` hands the model
four zonal MW numbers, *identical for every constraint in an hour* — 0085 §5.6's diagnosis
of why persistence beat us. NP1-346 is unit-level, so with the |SF| map it becomes genuinely
per-constraint:

    out_exposure[D, c] = Σ_sp |SF[c, sp]| · outage_MW_at_D[sp]

the same operation `geo.constraint_geography` uses to place a constraint in space — a
constraint's |SF| row says how strongly it feels congestion at each settlement point, so
the outaged MW it is exposed to is that row dotted with the outaged MW located at each SP.
This module reuses `geo`'s honest walk (`refit_grid`, the same window/refit/λ) rather than
writing a second one; the harness is the control.

**Two flavours, and the second is the point:**
  out_exposure_now      MW out in the newest snapshot admissible at DAM close (the D-4
                        vintage — posted_date ≤ D-1).
  out_exposure_planned  of that snapshot, only the MW whose Planned End Date ≥ D — i.e.
                        *expected still out on the delivery day*. This is the forward-
                        looking content Gate B found, and the thing RUC could not provide.

⚠ **LEAK TRAP — identical to 0088 commit 3, asserted below, not just commented.**
  * |SF| for delivery day D is fitted on the trailing window that closed **on or before D**
    (inherited from `geo_panel`'s structure: fit on [s-window, s), used for days ≥ s).
  * The outage snapshot is the **D-4 vintage** — the newest posted_date ≤ D-1, never a
    later one. NP1-346 posts ~05:00 CT, before the 10:00 DAM close, so a report posted on
    D-1 is admissible for delivery day D; one posted on D is not. A fresher snapshot leaks
    the future and *it will look like a result.*
"""
from __future__ import annotations

import bisect
import logging
from datetime import date

import numpy as np
import pandas as pd

from compute.mu_forecast.features import ERCOT_TZ
from compute.sf_map.geography.derive import (LAM, MIN_HOURS, REFIT_DAYS, STD_FLOOR, WINDOW_DAYS,
                           refit_grid)
from compute.sf_map.model.fit import implied_shift_factors

log = logging.getLogger("compute.mu_forecast.outage.exposure")

# Fuel buckets for the optional per-fuel split. Congestion responds differently to a
# thermal trip than a wind derate. Anything unlisted falls in "other" (coal, water, …).
FUEL_BUCKETS = {
    "Natural Gas": "gas", "Blast-Furnace Gas": "gas",
    "Wind": "wind", "Solar": "solar",
}


# --------------------------------------------------------------------------
# Locate the outaged MW — resource_outages rows onto settlement points
# --------------------------------------------------------------------------

def load_located_outages(conn, xwalk, sp_universe: set[str],
                         start: date, end: date) -> pd.DataFrame:
    """`resource_outages` rows over posted_dates `[start, end)`, located to SPs.

    `sp_universe` is the settlement-point space the SF lives in (the congestion panel's
    columns), so a located SP is guaranteed to be somewhere the |SF| map can weight it;
    a row the crosswalk cannot place there is dropped (unlocated MW, reported by commit 1,
    not silently absorbed). Returns long: (posted_date, sp, mw, planned_end, fuel)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT posted_date, resource_unit_code, resource_name,
                      effective_mw_reduction, planned_end_date, fuel_type
                 FROM resource_outages
                WHERE posted_date >= %s AND posted_date < %s""",
            (start, end))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["posted_date", "sp", "mw", "planned_end", "fuel"])

    out = []
    for posted, uc, rn, mw, planned_end, fuel in rows:
        sp, _ = xwalk.locate(uc, rn, sp_universe)
        if sp is None or mw is None:
            continue
        out.append((posted, sp, float(mw), planned_end, fuel))
    df = pd.DataFrame(out, columns=["posted_date", "sp", "mw", "planned_end", "fuel"])
    df["planned_end"] = pd.to_datetime(df["planned_end"], utc=True)
    return df


# --------------------------------------------------------------------------
# The exposure, on the honest walk
# --------------------------------------------------------------------------

def _exposure(W: pd.DataFrame, x: pd.Series) -> np.ndarray:
    """Σ_sp |SF[c, sp]| · x[sp] for every constraint. Zero where a constraint's |SF| mass
    lands on no outaged SP — a real zero (nothing out near it), distinct from the NaN a
    missing snapshot produces upstream."""
    if x.empty:
        return np.zeros(len(W))
    cols = W.columns.intersection(x.index)
    if cols.empty:
        return np.zeros(len(W))
    return W[cols].to_numpy(float) @ x.reindex(cols).to_numpy(float)


def _vintage(posted_sorted: list[date], d: pd.Timestamp) -> date | None:
    """The D-4 rule: newest posted_date ≤ D-1 (a report posted on D-1 ~05:00 CT is public
    before the D-1 10:00 DAM close for delivery day D; one posted on D is not)."""
    target = (pd.Timestamp(d).normalize() - pd.Timedelta(days=1)).date()
    i = bisect.bisect_right(posted_sorted, target) - 1
    return posted_sorted[i] if i >= 0 else None


def outage_exposure_panel(M: pd.DataFrame, C: pd.DataFrame, outages: pd.DataFrame,
                          days: pd.DatetimeIndex,
                          window_days: int = WINDOW_DAYS, refit_days: int = REFIT_DAYS,
                          lam: float = LAM, min_hours: int = MIN_HOURS,
                          anchor: pd.Timestamp | None = None,
                          by_fuel: bool = False) -> pd.DataFrame:
    """Per (delivery_day, constraint) outage exposure, from honestly-refit SFs.

    Mirrors `geo.geo_panel`: for each refit boundary `s`, fit `SF` on `[s - window, s)`
    (strictly before `s`) and use it for delivery days in `[s, s + refit_days)`. The one
    addition is the inner per-day step — pick the D-4 vintage snapshot and dot |SF| against
    its located MW — because exposure depends on the day's outages, not only the week's SF.

    `by_fuel` additionally emits `out_exposure_<bucket>` for the *planned* flavour."""
    if outages.empty:
        return pd.DataFrame()

    snaps = {p: g for p, g in outages.groupby("posted_date")}
    posted_sorted = sorted(snaps)

    grid = refit_grid(days, refit_days, anchor)
    frames, skipped = [], 0
    for s in grid:
        lo = s - pd.Timedelta(days=window_days)
        s_utc = s.tz_localize("UTC") if s.tzinfo is None else s
        lo_utc = lo.tz_localize("UTC") if lo.tzinfo is None else lo

        M_fit = M.loc[(M.index >= lo_utc) & (M.index < s_utc)]
        C_fit = C.loc[(C.index >= lo_utc) & (C.index < s_utc)]
        if M_fit.empty or C_fit.empty:
            skipped += 1
            continue
        SF = implied_shift_factors(M_fit, C_fit, lam=lam, min_hours=min_hours,
                                   standardize=True, std_floor=STD_FLOOR)
        if SF.empty:
            skipped += 1
            continue
        W = SF.abs()

        week_days = days[(days >= s) & (days < s + pd.Timedelta(days=refit_days))]
        for d in week_days:
            v = _vintage(posted_sorted, d)
            if v is None:
                continue                      # no admissible snapshot -> NaN after join
            # LEAK GUARDS — the two the plan says will look like a result if wrong.
            assert v <= (pd.Timestamp(d).normalize() - pd.Timedelta(days=1)).date(), (
                f"outage vintage {v} is not ≤ D-1 for delivery day {d.date()}")
            assert s <= d, f"SF boundary {s} fitted past delivery day {d}"

            snap = snaps[v]
            now = snap.groupby("sp")["mw"].sum()
            d_start = pd.Timestamp(d).tz_localize(ERCOT_TZ).tz_convert("UTC")
            still_out = snap[snap["planned_end"] >= d_start]
            planned = still_out.groupby("sp")["mw"].sum()

            f = pd.DataFrame({"out_exposure_now": _exposure(W, now),
                              "out_exposure_planned": _exposure(W, planned)},
                             index=SF.index)
            if by_fuel:
                for bucket in ("gas", "wind", "solar", "other"):
                    sub = still_out[still_out["fuel"].map(
                        lambda x: FUEL_BUCKETS.get(x, "other")) == bucket]
                    f[f"out_exposure_{bucket}"] = _exposure(W, sub.groupby("sp")["mw"].sum())
            f["delivery_day"] = d
            f.index.name = "key"
            frames.append(f.reset_index())

    if skipped:
        log.info("outage exposure: %d/%d refit boundaries had no fittable window",
                 skipped, len(grid))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).set_index(["delivery_day", "key"])
