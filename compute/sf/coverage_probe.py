"""S1.1 / R2 probe — is the SF coverage gap mostly seasonal memory?

The out-of-window harness (``experiments/ibp_out_of_window``) found that in a
typical week ~19% of the mu-mass driving congestion comes from constraints the
trailing-60d fit has no column for (implicit SF=0). Two mechanisms with
opposite fixes:

  * seasonal memory — the constraint DID bind in the past year, just not in the
    last 60 days. A warm-start (longer window / historical constraint priors)
    gives it a column back. No new modeling.
  * genuinely new — the constraint has no history at all. Only a faster refit
    cadence or a structural model helps.

This decomposes the *novel* mu-mass (binding in the scored week, absent from the
trailing fit) into those two buckets, using the extended NP4-191 history. It
needs only the shadow-price panel M (mu-mass and constraint presence) — no
congestion panel, no ridge fit.

Pass criterion: seasonal share of novel mass >= 0.60 resolves R2 favorably —
the gap closes with a warm-start, not a modeling project.

    docker compose run --rm compute python -m compute.sf.coverage_probe
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN
from compute.sf.panels import load_shadow_prices

log = logging.getLogger("compute.sf.coverage_probe")

DEFAULT_WINDOW_DAYS = 60
DEFAULT_REFIT_DAYS = 7
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_MIN_HOURS = 25
PASS_THRESHOLD = 0.60


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def probe(
    M: pd.DataFrame,
    window_days: int,
    refit_days: int,
    lookback_days: int,
    min_hours: int,
) -> pd.DataFrame:
    """One row per scored week with a full ``lookback_days`` of history behind."""
    day = pd.Timedelta(days=1)
    win = pd.Timedelta(days=window_days)
    look = pd.Timedelta(days=lookback_days)
    refit = pd.Timedelta(days=refit_days)

    days = pd.Index(M.index.normalize().unique()).sort_values()
    data_min, data_max = days[0], days[-1]
    # First scored week whose lookback window [s-365d, s-60d) fits in history.
    first = data_min + look
    starts = pd.date_range(first, data_max, freq=refit, inclusive="left")

    rows: list[dict] = []
    for s in starts:
        score_end = min(s + refit, data_max + day)

        # mu-mass per constraint over the scored week (mu >= 0; slack = 0).
        M_score = M.loc[(M.index >= s) & (M.index < score_end)]
        mass = M_score.clip(lower=0).sum(axis=0)
        mass = mass[mass > 0]
        total = float(mass.sum())
        if total <= 0:
            continue

        # Kept set: constraints the trailing-60d fit would keep (binding >= min_hours).
        M_win = M.loc[(M.index >= s - win) & (M.index < s)]
        kept = set(M_win.columns[(M_win > 0).sum() >= min_hours])

        novel_mass_s = mass[~mass.index.isin(kept)]
        novel_mass = float(novel_mass_s.sum())
        coverage = 1.0 - novel_mass / total

        # Historical lookback window, strictly before the trailing fit.
        M_hist = M.loc[(M.index >= s - look) & (M.index < s - win)]
        seen_any = set(M_hist.columns[(M_hist > 0).any()])
        seen_material = set(M_hist.columns[(M_hist > 0).sum() >= min_hours])

        seasonal_any = float(novel_mass_s[novel_mass_s.index.isin(seen_any)].sum())
        seasonal_material = float(
            novel_mass_s[novel_mass_s.index.isin(seen_material)].sum()
        )

        rows.append({
            "week": s.date(),
            "coverage": coverage,
            "total_mass": total,
            "novel_mass": novel_mass,
            "seasonal_any_mass": seasonal_any,
            "seasonal_material_mass": seasonal_material,
            "seasonal_any_share": seasonal_any / novel_mass if novel_mass > 0 else np.nan,
            "seasonal_material_share": seasonal_material / novel_mass if novel_mass > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=_parse_date, default=None,
                   help="Inclusive load start (default: earliest NP4-191 date).")
    p.add_argument("--end", type=_parse_date, default=None,
                   help="Exclusive load end (default: latest NP4-191 date + 1d).")
    p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                   help="Seasonal-memory lookback behind the trailing fit window.")
    p.add_argument("--min-binding-hours", type=int, default=DEFAULT_MIN_HOURS)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Default the load range to the full available NP4-191 history.
    with psycopg.connect(PG_DSN) as conn:
        if args.start is None or args.end is None:
            with conn.cursor() as cur:
                cur.execute("SELECT min(interval_ts)::date, max(interval_ts)::date "
                            "FROM ercot_dam_shadow_prices")
                dmin, dmax = cur.fetchone()
            start = args.start or dmin
            end = args.end or (dmax + timedelta(days=1))
        else:
            start, end = args.start, args.end
        log.info("loading shadow prices [%s, %s)", start, end)
        M = load_shadow_prices(conn, start, end)

    if M.empty:
        log.error("empty shadow-price panel over [%s, %s)", start, end)
        return 3
    log.info("M=%s", M.shape)

    df = probe(M, args.window_days, args.refit_days,
               args.lookback_days, args.min_binding_hours)
    if df.empty:
        log.error("no scored weeks had a full %d-day lookback", args.lookback_days)
        return 4

    pd.set_option("display.width", 200)
    print(df.to_string(index=False, float_format=lambda v: f"{v:10.3f}"))

    # Mass-weighted aggregates — the honest way to combine per-week shares.
    tot_novel = df["novel_mass"].sum()
    share_any = df["seasonal_any_mass"].sum() / tot_novel
    share_material = df["seasonal_material_mass"].sum() / tot_novel
    print(f"\n=== R2 probe over {len(df)} weeks "
          f"(lookback {args.lookback_days}d, min_hours {args.min_binding_hours}) ===")
    print(f"mean coverage (mu-mass with an SF column)     : {df.coverage.mean():.3f}")
    print(f"mean novel share (the gap)                    : {1 - df.coverage.mean():.3f}")
    print(f"seasonal share of novel mass  (bound at all)  : {share_any:.3f}")
    print(f"seasonal share of novel mass  (bound >= {args.min_binding_hours}h) : {share_material:.3f}")
    verdict = "SEASONAL — warm-start closes it" if share_any >= PASS_THRESHOLD \
        else "NOT mostly seasonal — needs faster refit / model"
    print(f"\nR2 verdict (>= {PASS_THRESHOLD:.2f} seasonal): {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
