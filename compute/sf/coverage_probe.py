"""Coverage-gap decomposition — what is the novel mu-mass actually made of?

In a typical week some of the mu-mass driving congestion falls on constraints
the trailing fit has no column for (implicit SF=0). At the operating point 0082
selected -- ``(240, 7, lambda=1)`` -- that gap is ~14% of mass. This splits it
into the three tiers that have three DIFFERENT fixes, and reports the ceiling on
what the cheapest of them can buy.

The tiers are keyed on what a **lifetime constraint library** could actually do,
not on whether the key was ever seen:

  * **A -- warm-startable.** Some EARLIER fit window kept this key, so a fitted
    SF row exists to inherit. This is the tier a warm-start closes; nothing else
    is. (Note this is strictly narrower than 0082's ``seen_material``: clearing
    ``min_hours`` inside a real fit window is the operational bar, not clearing
    it somewhere in a lookback band.)
  * **B -- seen, never fitted.** Bound at some point in history but never enough
    hours in any one window to be fitted. The library has nothing to inject; only
    a lower ``min_hours`` or a faster refit reaches these.
  * **C -- genuinely new.** No history at all. Irreducible -- flag honestly,
    widen bands.

``coverage_ceiling = 1 - (mass_B + mass_C) / mass_total`` is therefore the most
coverage a perfect warm-start could reach. **Gate G1 (plan/0084): build the
library only if ``coverage_ceiling - coverage >= 0.03``.** Below three points of
mu-mass the R2 payoff is inside week-to-week noise.

Two history modes:

  * **lifetime** (default) -- the band behind the fit window is all history to
    date. Weeks are admitted once ``--min-history-days`` of band sits behind the
    fit window; ``hist_days`` is emitted per week so a growing band is visible
    rather than silent.
  * **fixed lookback** (``--lookback-days``) -- the 0082/R2 band ``[s-lookback,
    s-window)`` and its two ``seasonal_*_share`` columns. Kept ONLY so that
    result stays reproducible: at ``--window-days 60 --lookback-days 365`` this
    reproduces R2's 0.507 / 0.303.

**Why the default moved.** R2 ran at ``window=60``, where the band
``[s-365d, s-60d)`` is 305 days. At ``window=240`` that same band is **125
days** -- a season, not a year -- so every share it reported at the real
operating point would be deflated by construction. The band was the bug, not the
number.

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
from compute.sf.config import REFIT_DAYS, WINDOW_DAYS
from compute.sf.panels import load_shadow_prices

log = logging.getLogger("compute.sf.coverage_probe")

# Semantic aliases retain the probe's vocabulary while sharing the adopted SF
# operating point it measures.
DEFAULT_WINDOW_DAYS = WINDOW_DAYS
DEFAULT_REFIT_DAYS = REFIT_DAYS
DEFAULT_MIN_HOURS = 25
DEFAULT_MIN_HISTORY_DAYS = 365

# plan/0084 gate G1, fixed before the run.
GATE_MIN_LIFT = 0.03

# RTC+B cutover. No pooled share without this split visible (handoff 3).
RTCB_DATE = pd.Timestamp("2025-12-05")

# Mass-weighted staleness buckets for tier A: how old the inherited SF row would
# be. Tunes (or kills) a decay factor later; do not build one on this alone.
AGE_BUCKETS = [(0, 30), (30, 90), (90, 180), (180, 10**6)]


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


class _BindCounts:
    """O(1) binding-hour counts over any day-aligned window.

    Every refit boundary needs one thing from the trailing window: how many hours
    each constraint bound, to compare against ``min_hours``. Slicing the panel to
    get it copies a (window_hours x constraints) float frame per boundary — ~140MB
    at a 240d window, and ``refit=1`` walks ~800 of them. A cumulative daily count
    answers the same question from a table 16x smaller than one such slice.

    Counts are integers, so this is EXACT, not an approximation: the kept sets it
    produces are identical to the ones the slicing version produced. Refit
    boundaries are day-aligned, so daily granularity loses nothing.
    """

    def __init__(self, M: pd.DataFrame) -> None:
        self.columns = M.columns
        daily = (M > 0).astype(np.int32).groupby(M.index.normalize()).sum()
        self.days = daily.index
        # Leading zero row so counts(lo, hi) is a plain difference.
        self.cum = np.vstack([
            np.zeros((1, len(self.columns)), dtype=np.int64),
            daily.to_numpy(dtype=np.int64).cumsum(axis=0),
        ])

    def counts(self, lo, hi) -> np.ndarray:
        i = self.days.searchsorted(lo, side="left")
        j = self.days.searchsorted(hi, side="left")
        return self.cum[j] - self.cum[i]

    def kept(self, lo, hi, min_hours: int) -> set:
        return set(self.columns[self.counts(lo, hi) >= min_hours])

    def seen(self, lo, hi) -> set:
        return set(self.columns[self.counts(lo, hi) > 0])


def _age_shares(ages: np.ndarray, mass: np.ndarray) -> dict:
    """Mass-weighted share of tier-A mass in each staleness bucket."""
    total = float(mass.sum())
    out = {}
    for lo, hi in AGE_BUCKETS:
        label = f"age_{lo}_{hi}" if hi < 10**6 else f"age_gt{lo}"
        sel = (ages >= lo) & (ages < hi)
        out[label] = float(mass[sel].sum()) / total if total > 0 else np.nan
    return out


def probe(
    M: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refit_days: int = DEFAULT_REFIT_DAYS,
    min_hours: int = DEFAULT_MIN_HOURS,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    """One row per scored week.

    Walks the refit grid forward, maintaining the two pieces of state a library
    would have at that moment -- ``ever_fitted`` (keys some earlier window kept,
    with the boundary it was last kept at) and ``ever_seen`` (keys that have
    bound at all). Both are strictly backward-looking: the fit at boundary ``s``
    is the CURRENT fit, so tier A counts only boundaries ``s' < s``. Accumulating
    after the row is emitted is what enforces that.

    ``lookback_days`` switches to the 0082/R2 fixed band and its legacy columns.
    """
    day = pd.Timedelta(days=1)
    win = pd.Timedelta(days=window_days)
    refit = pd.Timedelta(days=refit_days)
    legacy = lookback_days is not None
    look = pd.Timedelta(days=lookback_days or 0)

    days = pd.Index(M.index.normalize().unique()).sort_values()
    data_min, data_max = days[0], days[-1]

    # The refit grid's anchor decides which weeks get scored, so the legacy mode
    # must anchor exactly where R2 anchored (data_min + lookback) or it lands on
    # different weeks and the 0.507/0.303 comparison is not like-for-like.
    anchor = data_min + (look if legacy else win)
    starts = pd.date_range(anchor, data_max, freq=refit, inclusive="left")

    if not len(starts):
        return pd.DataFrame()
    bc = _BindCounts(M)

    # Library state, carried forward across boundaries.
    last_fitted: dict[str, pd.Timestamp] = {}   # key -> boundary last kept at

    rows: list[dict] = []
    for s in starts:
        # Everything that bound anywhere strictly before the scored week —
        # including inside the current fit window (a constraint that bound 3h
        # in-window was SEEN; it just wasn't fitted).
        ever_seen = bc.seen(data_min, s)

        score_end = min(s + refit, data_max + day)

        # The current fit's kept set: what this window would actually estimate.
        kept = bc.kept(s - win, s, min_hours)

        # mu-mass per constraint over the scored week (mu >= 0; slack = 0).
        M_score = M.loc[(M.index >= s) & (M.index < score_end)]
        mass = M_score.clip(lower=0).sum(axis=0)
        mass = mass[mass > 0]
        total = float(mass.sum())

        hist_days = int(((s - win) - data_min) / day)
        admitted = (s >= data_min + look) if legacy else (hist_days >= min_history_days)

        if total > 0 and admitted:
            novel_s = mass[~mass.index.isin(kept)]
            novel = float(novel_s.sum())
            coverage = 1.0 - novel / total

            row = {
                "week": s.date(),
                "hist_days": hist_days,
                "coverage": coverage,
                "total_mass": total,
                "novel_mass": novel,
                "n_novel_keys": int(novel_s.size),
                "post_rtcb": bool(s >= RTCB_DATE.tz_localize(s.tz)
                                  if s.tz else s >= RTCB_DATE),
            }

            # --- tiers (partition novel mass; A subset of seen by construction)
            a_keys = novel_s.index[novel_s.index.isin(last_fitted.keys())]
            rest = novel_s.drop(a_keys)
            b_keys = rest.index[rest.index.isin(ever_seen)]
            c_keys = rest.index.drop(b_keys)

            mass_a = float(novel_s[a_keys].sum())
            mass_b = float(novel_s[b_keys].sum())
            mass_c = float(novel_s[c_keys].sum())

            # The most a perfect warm-start could reach: B and C stay uncovered.
            ceiling = 1.0 - (mass_b + mass_c) / total

            ages = np.array([(s - last_fitted[k]) / day for k in a_keys], dtype=float)
            a_mass = novel_s[a_keys].to_numpy(dtype=float)
            row.update({
                "mass_warmstartable": mass_a,
                "mass_seen_unfitted": mass_b,
                "mass_new": mass_c,
                "share_warmstartable": mass_a / novel if novel > 0 else np.nan,
                "share_seen_unfitted": mass_b / novel if novel > 0 else np.nan,
                "share_new": mass_c / novel if novel > 0 else np.nan,
                "n_warmstartable": int(a_keys.size),
                "n_seen_unfitted": int(b_keys.size),
                "n_new": int(c_keys.size),
                "coverage_ceiling": ceiling,
                "ceiling_lift": ceiling - coverage,
                "mean_age_days": float(np.average(ages, weights=a_mass))
                                 if a_mass.sum() > 0 else np.nan,
                **_age_shares(ages, a_mass),
            })

            # --- legacy R2 band, for reproducibility of 0.507 / 0.303 only
            if legacy:
                seen_any = bc.seen(s - look, s - win)
                seen_material = bc.kept(s - look, s - win, min_hours)
                s_any = float(novel_s[novel_s.index.isin(seen_any)].sum())
                s_mat = float(novel_s[novel_s.index.isin(seen_material)].sum())
                row.update({
                    "seasonal_any_mass": s_any,
                    "seasonal_material_mass": s_mat,
                    "seasonal_any_share": s_any / novel if novel > 0 else np.nan,
                    "seasonal_material_share": s_mat / novel if novel > 0 else np.nan,
                })

            rows.append(row)

        # Accumulate AFTER emitting: the fit at `s` is the current one, so it
        # must not count as a prior fit for this week's tier A.
        for k in kept:
            last_fitted[k] = s

    return pd.DataFrame(rows)


def admission_stats(
    M: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refit_days: int = DEFAULT_REFIT_DAYS,
    min_hours: int = DEFAULT_MIN_HOURS,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
) -> dict:
    """Novel-constraint latency: how long from a constraint's first bind to its
    first SF column, under ``(window, refit, min_hours)``.

    The handoff's design target is ~1 day and nobody had measured the actual
    number. Two knobs gate admission and both are swept here: ``min_hours`` (the
    constraint must bind that many hours inside the window) and ``refit_days``
    (it can only be admitted at a refit boundary).

    ``blind_mass_share`` is the metric that matters — mu-mass that binds while
    the constraint still has no column, as a share of all mass over the region.
    Latency in days is the mechanism; blind mass is the damage, and it is what
    connects this directly to the coverage gap.

    **Censoring is handled by exclusion, not by pretending.** Keys already
    binding before the first refit boundary have no observable "first bind" (the
    panel starts mid-life), so they are dropped. Keys born late enough that they
    have not been admitted by the end of the panel are counted in
    ``admit_rate``/``never_admitted_mass`` but cannot contribute a latency.
    """
    day = pd.Timedelta(days=1)
    win = pd.Timedelta(days=window_days)
    refit = pd.Timedelta(days=refit_days)

    days = pd.Index(M.index.normalize().unique()).sort_values()
    data_min, data_max = days[0], days[-1]
    anchor = data_min + win
    starts = pd.date_range(anchor, data_max, freq=refit, inclusive="left")
    if not len(starts):
        return {}

    binding = M > 0
    # First bind per key. Keys never binding get NaT and drop out below.
    first_bind = binding.idxmax().where(binding.any(), pd.NaT)

    # Uncensored births only: the key's first bind must fall on-or-after the
    # first boundary, or we are measuring a lifetime that began before the data.
    born = first_bind[first_bind >= starts[0]].dropna()
    if born.empty:
        return {}

    bc = _BindCounts(M)
    first_col: dict[str, pd.Timestamp] = {}
    for s in starts:
        for k in bc.kept(s - win, s, min_hours):
            first_col.setdefault(k, s)

    end = data_max + day
    lat, blind, total_born_mass = [], [], []
    for k, f in born.items():
        c = first_col.get(k)
        # Mass that bound with no column: from first bind until admitted (or,
        # if never admitted, until the panel ends).
        stop = c if c is not None else end
        col = M[k]
        blind.append(float(col.loc[(col.index >= f) & (col.index < stop)]
                           .clip(lower=0).sum()))
        total_born_mass.append(float(col.clip(lower=0).sum()))
        if c is not None:
            lat.append((c - f) / day)

    lat = np.array(lat, dtype=float)
    blind_mass = float(np.sum(blind))
    # Denominator: all mass over the region a column could have covered.
    M_region = M.loc[M.index >= anchor]
    region_mass = float(M_region.clip(lower=0).to_numpy(dtype=float).sum())
    never = [b for k, b in zip(born.index, total_born_mass) if k not in first_col]

    cov = probe(M, window_days, refit_days, min_hours, min_history_days)
    return {
        "window_days": window_days,
        "refit_days": refit_days,
        "min_hours": min_hours,
        "n_new_keys": int(born.size),
        "n_admitted": int(sum(k in first_col for k in born.index)),
        "admit_rate": float(sum(k in first_col for k in born.index) / born.size),
        "median_latency_days": float(np.median(lat)) if lat.size else np.nan,
        "p90_latency_days": float(np.percentile(lat, 90)) if lat.size else np.nan,
        "blind_mass_share": blind_mass / region_mass if region_mass > 0 else np.nan,
        "never_admitted_mass_share": (float(np.sum(never)) / region_mass
                                      if region_mass > 0 else np.nan),
        "coverage": float(cov["coverage"].mean()) if not cov.empty else np.nan,
        "n_weeks": int(len(cov)),
    }


def _summarize(df: pd.DataFrame, label: str, min_hours: int, legacy: bool) -> None:
    """Mass-weighted aggregates -- the honest way to combine per-week shares."""
    novel = df["novel_mass"].sum()
    print(f"\n=== {label} — {len(df)} weeks "
          f"(hist band {df.hist_days.min()}–{df.hist_days.max()}d) ===")
    print(f"coverage (mu-mass with a fitted SF column) : {df.coverage.mean():.3f}")
    print(f"novel share (the gap)                      : {1 - df.coverage.mean():.3f}")
    print("novel mass by tier (mass-weighted):")
    print(f"  A  warm-startable  (a prior fit kept it) : "
          f"{df.mass_warmstartable.sum() / novel:.3f}")
    print(f"  B  seen, never fitted                    : "
          f"{df.mass_seen_unfitted.sum() / novel:.3f}")
    print(f"  C  genuinely new                         : "
          f"{df.mass_new.sum() / novel:.3f}")
    print(f"coverage ceiling (perfect warm-start)      : "
          f"{df.coverage_ceiling.mean():.3f}")
    lift = df.coverage_ceiling.mean() - df.coverage.mean()
    print(f"  → achievable lift                        : {lift:+.3f}")
    print("tier-A staleness (share of A mass by age of the inherited row):")
    for lo, hi in AGE_BUCKETS:
        col = f"age_{lo}_{hi}" if hi < 10**6 else f"age_gt{lo}"
        print(f"  {col:<12} : {df[col].mean():.3f}")
    if legacy:
        print(f"[legacy R2 band] seasonal share, bound at all   : "
              f"{df.seasonal_any_mass.sum() / novel:.3f}")
        print(f"[legacy R2 band] seasonal share, bound >= {min_hours}h : "
              f"{df.seasonal_material_mass.sum() / novel:.3f}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=_parse_date, default=None,
                   help="Inclusive load start (default: earliest NP4-191 date).")
    p.add_argument("--end", type=_parse_date, default=None,
                   help="Exclusive load end (default: latest NP4-191 date + 1d).")
    p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--min-binding-hours", type=int, default=DEFAULT_MIN_HOURS)
    p.add_argument("--min-history-days", type=int, default=DEFAULT_MIN_HISTORY_DAYS,
                   help="Admit a week once this much history sits behind its fit "
                        "window. Lifetime mode only.")
    p.add_argument("--lookback-days", type=int, default=None,
                   help="Use the 0082/R2 fixed band [s-lookback, s-window) and "
                        "emit its seasonal_* columns instead of a lifetime band. "
                        "At --window-days 60 --lookback-days 365 this reproduces "
                        "R2's 0.507/0.303.")
    p.add_argument("--emit-latency", action="store_true",
                   help="Instead of the tier table, sweep the two admission "
                        "knobs (--refit-grid x --min-hours-grid) and report "
                        "novel-constraint latency, blind mu-mass and coverage "
                        "for each. Needs no ridge fits — the ACCURACY guard on "
                        "any move comes from sweep_sf, not from here.")
    p.add_argument("--refit-grid", default="1,3,7")
    p.add_argument("--min-hours-grid", default="5,10,25")
    p.add_argument("--out", type=str, default=None,
                   help="Write the per-week rows to CSV.")
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

    if args.emit_latency:
        rows = []
        for r in (int(x) for x in args.refit_grid.split(",") if x.strip()):
            for mh in (int(x) for x in args.min_hours_grid.split(",") if x.strip()):
                log.info("admission: window=%d refit=%d min_hours=%d",
                         args.window_days, r, mh)
                st = admission_stats(M, args.window_days, r, mh,
                                     args.min_history_days)
                if st:
                    rows.append(st)
        grid = pd.DataFrame(rows)
        print(grid.to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
        print("\nmedian/p90 latency = days from a new constraint's first bind to "
              "its first SF column.\nblind_mass_share = mu-mass that bound while "
              "the constraint still had no column.\nCurrent operating point is "
              f"refit=7, min_hours={DEFAULT_MIN_HOURS}. A move needs the OOS "
              "accuracy guard from sweep_sf.")
        if args.out:
            grid.to_csv(args.out, index=False)
            log.info("wrote %s", args.out)
        return 0

    legacy = args.lookback_days is not None
    df = probe(M, args.window_days, args.refit_days, args.min_binding_hours,
               args.min_history_days, args.lookback_days)
    if df.empty:
        log.error("no scored weeks cleared the history requirement "
                  "(window %dd, min-history %dd)",
                  args.window_days, args.min_history_days)
        return 4

    pd.set_option("display.width", 250)
    show = [c for c in ("week", "hist_days", "coverage", "coverage_ceiling",
                        "ceiling_lift", "share_warmstartable",
                        "share_seen_unfitted", "share_new", "mean_age_days",
                        "n_novel_keys") if c in df.columns]
    print(df[show].to_string(index=False, float_format=lambda v: f"{v:9.3f}"))

    mode = (f"fixed lookback {args.lookback_days}d" if legacy else "lifetime band")
    _summarize(df, f"coverage decomposition — window {args.window_days}d, "
                   f"refit {args.refit_days}d, min_hours {args.min_binding_hours}, "
                   f"{mode}", args.min_binding_hours, legacy)

    # RTC+B split. Suggestive-vs-clean caveat: at window=240 the post-cutover fit
    # windows still straddle the cutover.
    for post, sub in df.groupby("post_rtcb"):
        if len(sub) < 2:
            continue
        _summarize(sub, f"{'POST' if post else 'PRE'}-RTC+B",
                   args.min_binding_hours, legacy)

    if args.out:
        df.to_csv(args.out, index=False)
        log.info("wrote %s", args.out)

    # --- Gate G1 (plan/0084), fixed before the run and not edited after.
    lift = df.coverage_ceiling.mean() - df.coverage.mean()
    verdict = ("PASS — build the library (commits 3–4)" if lift >= GATE_MIN_LIFT
               else "FAIL — warm-start cannot buy enough; skip to the "
                    "latency/admission work")
    print(f"\n=== GATE G1 (achievable coverage lift >= {GATE_MIN_LIFT:.2f}) ===")
    print(f"coverage {df.coverage.mean():.3f} → ceiling "
          f"{df.coverage_ceiling.mean():.3f}  (lift {lift:+.3f})")
    print(f"G1: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
