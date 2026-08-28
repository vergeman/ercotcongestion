"""Constraint geography, via the |SF|-weighted centroid.

A constraint key is an opaque string (`ConstraintName|ContingencyName`). The
model knows how often it bound and how big, but nothing about where it is.

Every covariate it has (load, wind, solar, outages) is system-wide or zonal,
identical for every constraint in a given hour: the model cannot tell two
constraints apart except by their own history, which is why persistence - which
implicitly carries topology state - tends to beat the model: because a line out
yesterday is still out today.

Shadow-price rows carry `from_station`/`to_station`, and it's tempting to join
those to plant names. But only ~4.3% of binding μ-mass join; those are *plant*
names, while constraint endpoints are *transmission substations*. They're
different namespaces.

But have a map from constraints to space: `SF` itself. The shift-factor row for
a constraint says how strongly it pushes congestion at every settlement point,
and settlement points have coordinates. The |SF|-weighted centroid of those
coordinates is *the market's own estimate* of where the constraint lives,
recovered from prices, with no crosswalk, no geocoding of station names, and no
namespace to reconcile.

Trap: using a global SF calculation to identify a constraint location
throughout the entire dataset. SF is calculated and fitted per window, and
contributes depending on the bind - so location can change weekly. Recall this
isn't realism, not trying to locate a constraint, but generate a feature for
mu.

Geography data components:

  coordinates   `data/processed/settlement_points_geocoded.csv` — 1,092 SPs with
                lat/lon, covering 97.9% of the 1,115 SPs in the congestion panel.

  zone + kV     `data/raw/ercot_geocode/Settlement_Points_*.csv`, joined on
                `RESOURCE_NODE` (*not* `NODE_NAME`, which is the electrical bus
                and matches zero settlement points) — 1,024 SPs, 91.8%, each
                mapping to exactly one zone and one voltage.

  zone anchors  the four load zones' reference points are the mean position of
                their own settlement points, derived from the data above, so
                there is not one hand-typed coordinate in this file.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from compute.sf_map.model.fit import implied_shift_factors
from compute.time import normalize_ct_day

log = logging.getLogger("compute.sf_map.geography.derive")

SP_COORDS = Path("/data/processed/settlement_points_geocoded.csv")
SP_META = Path("/data/raw/ercot_geocode/Settlement_Points_06112026_122819.csv")

# The SF operating point, single-sourced in `compute.sf_map.config` — the same fit the
# scoring harness uses for the week a delivery day belongs to. Identical to
# `score.py`'s import, and that shared source is the point.
from compute.sf_map.config import (  # noqa: E402
    MIN_HOURS, REFIT_DAYS, RIDGE_LAMBDA as LAM, WINDOW_DAYS,
)
STD_FLOOR = 100.0

EARTH_R_KM = 6371.0

# ERCOT's four load zones, as they appear in SETTLEMENT_LOAD_ZONE.
ZONES = ("LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST")


# --------------------------------------------------------------------------
# The reference geography
# --------------------------------------------------------------------------

def load_sp_geography(coords_path: Path = SP_COORDS,
                      meta_path: Path = SP_META) -> pd.DataFrame:
    """Settlement point → (lat, lon, zone, kv). Indexed by settlement point.

    Two files, two different keys, and getting the second one wrong is silent: the
    metadata file's `NODE_NAME` is the **electrical bus** and joins to **0** of the
    1,115 settlement points in the congestion panel, while `RESOURCE_NODE` joins to
    1,024. A left join on the wrong column produces an all-NaN zone column and a
    geography arm that quietly does nothing — so the join is asserted, not assumed.
    """
    coords = pd.read_csv(coords_path)[["settlement_point", "lat", "lon"]]
    coords = coords.dropna().set_index("settlement_point")

    meta = pd.read_csv(meta_path)[["RESOURCE_NODE", "SETTLEMENT_LOAD_ZONE",
                                   "VOLTAGE_LEVEL"]].dropna(subset=["RESOURCE_NODE"])
    meta = (meta.drop_duplicates("RESOURCE_NODE")
                .set_index("RESOURCE_NODE")
                .rename(columns={"SETTLEMENT_LOAD_ZONE": "zone",
                                 "VOLTAGE_LEVEL": "kv"}))

    sp = coords.join(meta, how="left")
    if not sp["zone"].notna().any():
        raise ValueError(
            "no settlement point matched the zone metadata — the join key is wrong. "
            "It is RESOURCE_NODE; NODE_NAME is the electrical bus and matches none.")
    log.info("SP geography: %d with coords, %d with zone/kV",
             len(sp), int(sp["zone"].notna().sum()))
    return sp


def zone_anchors(sp: pd.DataFrame) -> pd.DataFrame:
    """A reference point per load zone: the mean position of its own settlement points.

    Derived rather than typed. It is a crude centre — SP density is not population
    density — but it is *reproducible from the data*, and the feature it feeds
    (distance from the constraint's centroid to each zone) only needs a stable
    reference, not a survey-grade one.
    """
    return sp.dropna(subset=["zone"]).groupby("zone")[["lat", "lon"]].mean()


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance in km. Texas is ~1,200 km across; a flat-earth
    approximation would be off by kilometres at the corners, and it costs nothing
    to just do it properly."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# --------------------------------------------------------------------------
# The centroid
# --------------------------------------------------------------------------

def constraint_geography(SF: pd.DataFrame, sp: pd.DataFrame) -> pd.DataFrame:
    """|SF|-weighted geography, one row per constraint in `SF`.

    `SF` is (constraints × settlement points). The weights are |SF|: a shift
    factor's sign says which way the constraint pushes price, its magnitude
    says how hard. Where a constraint lives is about (abs) magnitude only.

    Columns (all prefixed `geo_`, which is how the ablation selects them):

      geo_lat/geo_lon    the eletrical centroid — implied location estimate

      geo_spread_km      |SF|-weighted RMS distance from that centroid. A local
                         constraint and a system-wide one are different objects,
                         and the centroid alone cannot tell them apart: a constraint
                         with mass in Amarillo and Brownsville has a centroid near
                         Austin but lives in neither. lo - close, hi - distributed.

      geo_sp_eff         effective number of settlement points: 1 / sum(weights^2)
                         1 / sum(w1^2 + w2^2...)
                         Measures concentration, while geo_spread_km measures extent

      geo_kv_mean/max    voltage class, |SF|-weighted. 345 kV backbone vs 138 kV.

      geo_zone_<z>       share of |SF| mass in each load zone. The constraint's
                         exposure expressed in the same zones the load forecast
                         is published in. This enabled model to connect "the
                         north zone is hot today" to "this constraint".
                         geo_dist_<z> km from the centroid to each zone's
                         anchor.

    A constraint whose |SF| mass lands entirely on settlement points we have no
    coordinates for gets **NaN, not a fallback**. It is a real hole; `build_panel`'s
    law is that holes stay holes, and the gradient booster reads NaN natively.

    """

    known = SF.columns.intersection(sp.index)  # matching sp (our geolocation sp data and in SF)
    if known.empty:
        return pd.DataFrame(index=SF.index)

    W = SF[known].abs().to_numpy(float, copy=True)  # W "weights" = filter and copy SF to known sp - (Note abs)
    W[~np.isfinite(W)] = 0.0                        # clean W: missing, nan, inifite -> 0.0
    g = sp.loc[known]                               # g "geography" = filtered sp's to known

    total = W.sum(axis=1)                           # single num per constraint
                                                    # constraint x sum(sp) - (axis=1 horizontal sum)

    ok = total > 0                                  # constraints[bool]

    # P: row-normalised "(P) probability like" weights. `where` keeps the
    # all-zero rows from dividing by zero;
    #
    # constraint x sp; W normalized by np.where
    #    np.where(condition, X true, Y false) x if condition, else Y
    P = W / np.where(ok, total, 1.0)[:, None]

    #
    # CALC WEIGHTED AVG LAT/LNG COORDINATES
    #
    # geo_spread_km: spread - weighted RMS (root mean square) distance from
    # weighted electric centroid. RMS emphasizes more distant points.
    #
    # geo_sp_eff: sp_eff:  effective settlement point
    # how many settlement points are represented by a constraint’s SF weights
    # node = 1 / sum(P**2):

    lat = P @ g["lat"].to_numpy(float)
    lon = P @ g["lon"].to_numpy(float)

    # d: distance matrix - constraint x sp, val km
    d = haversine_km(lat[:, None], lon[:, None],
                     g["lat"].to_numpy(float)[None, :],
                     g["lon"].to_numpy(float)[None, :])

    spread = np.sqrt((P * d ** 2).sum(axis=1))

    sp_eff = 1.0 / np.maximum((P ** 2).sum(axis=1), 1e-12)

    out = pd.DataFrame({"geo_lat": lat, "geo_lon": lon,
                        "geo_spread_km": spread,
                        "geo_sp_eff": sp_eff},
                       index=SF.index)

    #
    # KV
    #
    # geo_kv_mean
    # geo_kv_max
    #

    kv = g["kv"].to_numpy(float)
    has_kv = np.isfinite(kv)

    # Renormalise over the SPs that HAVE a voltage, so a constraint is not penalised
    # for sitting partly on nodes whose kV we happen not to know.
    # simply exclude sp's with no kv
    Wk = W[:, has_kv]
    tk = Wk.sum(axis=1)  # "total known kv" horizontal sum (across cols)
    okk = tk > 0         # mask
    Pk = Wk / np.where(okk, tk, 1.0)[:, None]
    out["geo_kv_mean"] = np.where(okk, Pk @ kv[has_kv], np.nan)   # mean because normalized above

    # The heaviest-weighted single node's voltage:
    # SF max (highest weighted exposure) not max raw kv
    top = kv[has_kv][np.argmax(Wk, axis=1)] if has_kv.any() else np.full(len(SF), np.nan)
    out["geo_kv_max"] = np.where(okk & (Wk.max(axis=1) > 0), top, np.nan)


    #
    # ZONES
    #
    # geo_zone_<zone>: share of a constraint’s SF exposure per <zone>
    # settlement points
    #
    # geo_dist_<zone>: distance from the constraint’s exposure centroid to the
    # <zone> anchor
    #

    zone = g["zone"].to_numpy()
    for z in ZONES:
        m = (zone == z)
        out[f"geo_zone_{z.removeprefix('LZ_').lower()}"] = (
            W[:, m].sum(axis=1) / np.where(ok, total, 1.0) if m.any() else np.nan)


    anchors = zone_anchors(sp)    # mean lat/lng from points assigned in zone
    for z in ZONES:
        if z not in anchors.index:
            continue
        a = anchors.loc[z]
        out[f"geo_dist_{z.removeprefix('LZ_').lower()}"] = haversine_km(
            lat, lon, a["lat"], a["lon"])

    # Constraints with no mass on any known coordinate: honest NaN
    out.loc[~ok, :] = np.nan
    return out


def constraint_type(geo: pd.DataFrame) -> pd.Series:
    """Classify each constraint's *form* from fields already derived per window,
    so the overview can pick a mark: gtc / transmission / radial.

    * gtc: the contingency component of the `constraint_key`
      (constraint_name|contingency_name) is BASE CASE: a generic /
      interface constraint with a large regional footprint (drawn as a region).

    * radial: n_rail >= 1 AND peak_offrail < 0.25: a rail with little
      graded body beneath it, a pocket/resource (drawn as a point).

      * "Rail": RAIL_CAP = 0.999, so "railed" is when SF is pinned to magnitude 1.0
      * n_rail: number of railed
      * peak_offrail: largest value (abs) that's not railed.

      -> one settlement point dominates at 1.0, with little distributed SF structure
      beneath it. localized pocket/resource-style constraint and draws it as a
      point - radial.

    * transmission: everything else: a real line + real contingency,
      co-located (drawn as an MST corridor).

    """
    contingency = geo.index.to_series().str.split("|", n=1).str[-1].str.strip().str.upper()
    nr = geo["n_rail"].fillna(0)
    po = geo["peak_offrail"].fillna(0.0)

    ctype = pd.Series("transmission", index=geo.index)
    ctype[(nr >= 1) & (po < 0.25)] = "radial"

    ctype[contingency == "BASE CASE"] = "gtc"  # last: a BASE CASE is always gtc
    return ctype


def refit_grid(days: pd.DatetimeIndex, refit_days: int = REFIT_DAYS,
               anchor: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    """Weekly SF-refit boundaries covering `days`, phase-locked to `anchor`.

    "grid" is a synchronized, recurring date range (anchor - 7, anchor, anchor
    + 7, anchor + 14...)

    `anchor` is normally the first **scored** week; goal is to have the
    geography's date boundaries coincide with the scoring harness's, so the SF
    behind a scored week's geography is the same fit `score.py` uses for that
    week, and not one up to six days staler.

    The grid extends *backwards* from the anchor to cover the training margin
    (lo, hi), which needs geography too.

    """
    lo, hi = days.min(), days.max()
    a = pd.Timestamp(anchor).tz_localize(None).normalize() if anchor is not None else lo
    step = pd.Timedelta(days=refit_days)
    back = int(np.ceil(max((a - lo) / step, 0)))
    return pd.date_range(a - back * step, hi, freq=step)


def geo_panel(M: pd.DataFrame, C: pd.DataFrame, days: pd.DatetimeIndex,
              sp: pd.DataFrame | None = None,
              window_days: int = WINDOW_DAYS, refit_days: int = REFIT_DAYS,
              lam: float = LAM, min_hours: int = MIN_HOURS,
              anchor: pd.Timestamp | None = None,
              on_refit=None) -> pd.DataFrame:
    """Per (delivery_day, constraint) geography, from SFs.

    This function takes the raw panels and fits the SF itself. It does not
    accept an `SF` argument, so we don't contaminate our panel using an SF with
    a constraint that wasn't seen at that time. Remember this a electric
    "exposure centroid", so it's not static, but generated from the weekly SF.
    Some constraints may disappear, or "move" because of different weights.

    For each refit boundary `s`, `SF` is fitted on the window `[s -
    window_days, s)` and used for the delivery days in `[s, s + refit_days)`.
    So a delivery day `d` is always described by a map fitted on data that
    closed on or before `d`.

    Days before the first boundary with a fittable window get no rows; the left
    join in `build_panel` gives a NaN geography. For the earliest training
    margin, where the congestion panel (which starts 2025-01-01, months after
    the shadow prices) cannot support a fit at all.

    """

    # sp -> (lat, lon, zone, kv) via csv data lookups
    sp = load_sp_geography() if sp is None else sp

    # grid: is a pd.DatetimeIndex; synchronized b/w SF weekly refit and mu walk
    # forward refit) recurrent step date range (list of dates)
    grid = refit_grid(days, refit_days, anchor)

    frames, skipped = [], 0
    for s in grid:
        lo = s - pd.Timedelta(days=window_days)
        s_utc = normalize_ct_day(s)
        lo_utc = normalize_ct_day(lo)

        M_fit = M.loc[(M.index >= lo_utc) & (M.index < s_utc)]
        C_fit = C.loc[(C.index >= lo_utc) & (C.index < s_utc)]
        if M_fit.empty or C_fit.empty:
            skipped += 1
            continue

        SF = implied_shift_factors(M_fit, C_fit,
                                   lam=lam,  # lam is penalty for ridge regression
                                   min_hours=min_hours,
                                   standardize=True,
                                   std_floor=STD_FLOOR)
        if SF.empty:
            skipped += 1
            continue

        g = constraint_geography(SF, sp)     # sets geo_* features

        # NB: two masks (&) to yield list of days
        week_days = days[(days >= s) & (days < s + pd.Timedelta(days=refit_days))]

        # on_refit is our callback "attach_refit_features", where we append our
        # geographical data
        if on_refit is not None:
            on_refit(week_days, g)
        else:
            for d in week_days:
                f = g.copy()
                f["delivery_day"] = d
                f.index.name = "key"
                frames.append(f.reset_index())

        log.info("  geo %s: SF %s → %d constraints located",
                 s.date(), SF.shape, int(g["geo_lat"].notna().sum()))

    if skipped:
        log.info("geo: %d/%d refit boundaries had no fittable window "
                 "(expected at the start — C begins months after M)",
                 skipped, len(grid))
    if on_refit is not None or not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).set_index(["delivery_day", "key"])


# --------------------------------------------------------------------------
# Coverage — reported in μ-mass, because key count flatters
# --------------------------------------------------------------------------

def coverage_by_mu_mass(M: pd.DataFrame, geo: pd.DataFrame,
                        days: pd.DatetimeIndex) -> pd.DataFrame:
    """What fraction of *binding μ-mass* has a centroid — not what fraction of keys.

    **The acceptance criterion says μ-mass and it means it.** The two numbers are
    very different and the flattering one is the wrong one: the SF fit drops any
    constraint binding under `min_hours` in the window, so a large share of *keys*
    is unlocated, while the keys that carry the μ are exactly the ones that bind
    often enough to be fitted. Reporting key count here would understate the arm;
    reporting μ-mass says what the score is actually made of.
    """
    from compute.mu_forecast.panel.availability import delivery_day_of

    # The located set is keyed by delivery day. `geo` carries `geo_lat` only when
    # the week's SF actually placed the constraint.
    located = {pd.Timestamp(d): set(g.index.get_level_values("key")[
                   g["geo_lat"].notna().to_numpy()])
               for d, g in geo.groupby(level="delivery_day")}

    day_of = pd.DatetimeIndex(delivery_day_of(M.index))
    rows = []
    for d in days:
        m = M.loc[day_of == pd.Timestamp(d)]
        if m.empty:
            continue
        mass = m.abs().sum()
        binding = mass[mass > 0]
        total = float(binding.sum())
        if total <= 0:
            continue
        keys = located.get(pd.Timestamp(d), set())
        hit = binding.reindex(sorted(keys & set(binding.index))).sum()
        rows.append({"delivery_day": d, "mu_mass": total,
                     "mass_located": float(hit) / total,
                     "keys_located": len(keys & set(binding.index)),
                     "keys_binding": int(len(binding))})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    """Report centroid coverage — the acceptance criterion, standalone.

        docker compose run --rm compute python -m compute.sf_map.geography.derive
    """
    import argparse
    import os

    import psycopg

    from compute.mu_forecast.panel.availability import delivery_day_of
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default="2025-08-14")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)

    days = pd.DatetimeIndex(np.unique(delivery_day_of(M.index)))
    geo = geo_panel(M, C, days, anchor=pd.Timestamp(args.score_from))
    cov = coverage_by_mu_mass(M, geo, days)

    scored = cov[cov["delivery_day"] >= pd.Timestamp(args.score_from)]
    print("\n=== CENTROID COVERAGE (of binding μ-mass, not key count) ===")
    print(f"  all days     {cov['mass_located'].mean():.3f}   "
          f"({cov['keys_located'].mean():.0f}/{cov['keys_binding'].mean():.0f} keys/day)")
    print(f"  scored days  {scored['mass_located'].mean():.3f}   "
          f"({scored['keys_located'].mean():.0f}/{scored['keys_binding'].mean():.0f})")
    print(f"\n  R4's failed station-name join reached 0.043 of μ-mass. "
          f"That is the bar this replaces.")
    if args.out:
        cov.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
