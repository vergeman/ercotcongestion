"""The ablation — one panel, one harness, five arms.

plan/0088 commit 5.

**The rule this file exists to enforce: the ONLY thing that varies between rows of
the output table is the feature set.** Everything else — the panel, the weeks, the SF
map, the operating point `(240, 7, λ=1)`, the metric functions — is held fixed, by
construction rather than by care:

  * the panel is built **once**, here, with every arm's columns present, and each arm
    is a **column mask** over that one object (`mu_model.feature_cols`). Rebuilding it
    per arm would leave five separately-constructed panels whose differences are not
    *guaranteed* to be only the arm;
  * scoring goes through **`compute/mu/score.py`, unchanged and unimported-around**.
    The whole reason 0085's numbers are trustable is that there is exactly one
    harness, and 0088 does not get to write a second one;
  * the baselines (oracle, persistence, climatology, null) do not depend on the arm at
    all — so they are **asserted identical across arms** rather than assumed. If
    persistence moves between two arms, something is wrong with the harness and the
    whole table is void. That check has teeth: it is the cheapest possible detector
    of the class of bug that has bitten this project twice (a drifting refit grid).

**Read the result against `plan/s6-gate.md`, which was written before any of these
numbers existed.** Two bars, and they are different questions:

  * **existence** — beat persistence (top-decile **0.561**);
  * **product (§5.5)** — top-decile **≥ 0.60**.

Persistence's own top-decile is *below* the product bar, so an arm can win the
existence test, absorb persistence entirely, and **still not ship a product**. The
report prints both bars next to every arm so that reading is unavoidable.

    docker compose run --rm compute python -m compute.experiments.mu.feature_ablation \
      --score-from 2025-08-14 --out /compute/mu/ablation.csv
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from compute.mu import score as score_mod
from compute.mu.mu_model import (DEFAULT_REFIT_DAYS, DEFAULT_TRAIN_DAYS,
                                 FEATURE_SETS, arms_for, feature_cols, load_preds,
                                 save_preds, walk_forward)

log = logging.getLogger("compute.experiments.mu.feature_ablation")

ARMS = ["base", "lag", "geo", "wx", "all"]

# The bars, copied from plan/s6-gate.md. Pre-registered; not editable here.
PERSISTENCE_TOPDEC = 0.561
PRODUCT_TOPDEC = 0.60

# Baselines must be bit-identical across arms. Float noise in the SF solve is real
# but tiny; anything above this is a structural difference, not arithmetic.
BASELINE_TOL = 1e-9


def run_arm(panel: pd.DataFrame, arm: str, preds_path: Path,
            train_days: int, refit_days: int,
            score_from: pd.Timestamp | None, anchor: pd.Timestamp,
            resume: bool = True) -> pd.DataFrame:
    """Walk one arm over the shared panel. Cached by `preds_path` so a crash in
    arm 4 does not re-pay for arms 1-3 — this is a multi-hour loop."""
    if resume and preds_path.exists():
        log.info("arm %-5s: reusing %s", arm, preds_path.name)
        return load_preds(str(preds_path))

    arms = arms_for(arm)
    cols = feature_cols(panel, arms)
    log.info("arm %-5s: %d features (%s)", arm, len(cols) + 1,
             ", ".join(arms) if arms else "base only")

    t0 = time.perf_counter()
    preds, _ = walk_forward(panel, train_days, refit_days, score_from,
                            anchor=anchor, arms=arms)
    if preds.empty:
        raise RuntimeError(f"arm {arm!r} produced no predictions")

    save_preds(str(preds_path), preds)
    log.info("arm %-5s: %s rows in %.0fm → %s", arm, f"{len(preds):,}",
             (time.perf_counter() - t0) / 60, preds_path.name)
    return preds


def check_baselines_identical(df: pd.DataFrame) -> None:
    """The baselines cannot depend on the arm. Prove it, do not assume it.

    Oracle, persistence, climatology and null are computed from `M`, `C` and the SF
    map alone — the model's predictions never touch them. So if two arms disagree
    about persistence, the two arms were not scored on the same weeks or the same
    map, and **every comparison in the table is meaningless.** This is the cheapest
    available detector of a misphased grid, which has already gone wrong twice.
    """
    base = [s for s in score_mod.SOURCES if s != "model"]
    a = df[(df["regime"] == "all") & (df["source"].isin(base))]
    piv = a.pivot_table(index=["source", "week"], columns="arm",
                        values="topdecile_hit", dropna=False)
    spread = (piv.max(axis=1) - piv.min(axis=1)).abs()
    bad = spread[spread > BASELINE_TOL].dropna()
    if len(bad):
        raise RuntimeError(
            f"baselines differ across arms — the harness is not held fixed and the "
            f"ablation is void. Worst: {bad.sort_values().tail(3).to_dict()}")
    log.info("baselines identical across all %d arms ✓", df["arm"].nunique())


# --------------------------------------------------------------------------
# reporting — both bars, every arm, always
# --------------------------------------------------------------------------

def _row(d: pd.DataFrame, label: str) -> str:
    if d.empty:
        return f"  {label:<14} {'—':>7}"
    td = d.topdecile_hit.mean()
    # The two verdicts, printed rather than left to the reader's optimism.
    mark = ("PRODUCT" if td >= PRODUCT_TOPDEC else
            "alive" if td > PERSISTENCE_TOPDEC else "")
    return (f"  {label:<14} {d.pooled_r2.mean():>7.3f} {d.mae.mean():>8.2f} "
            f"{d.rank_spearman.mean():>9.3f} {d.sign_agree.mean():>7.3f} "
            f"{td:>8.3f}   {mark}")


def _table(df: pd.DataFrame, title: str) -> str:
    out = [f"\n{title}",
           f"  {'arm':<14} {'R2':>7} {'MAE':>8} {'Spearman':>9} {'sign':>7} "
           f"{'top-dec':>8}   verdict"]
    for arm in ARMS:
        out.append(_row(df[(df["arm"] == arm) & (df["source"] == "model")],
                        f"model:{arm}"))
    out.append("  " + "-" * 60)
    # The baselines are arm-invariant, so read them off any arm.
    one = df[df["arm"] == ARMS[0]]
    for src in ("persistence", "climatology", "oracle"):
        out.append(_row(one[one["source"] == src], src))
    return "\n".join(out)


def report(df: pd.DataFrame, bands: pd.DataFrame | None = None) -> str:
    a = df[df["regime"] == "all"]
    out = [_table(a, "=== ABLATION: ALL 46 WEEKS ===")]

    pre, post = a[a["week"] < score_mod.RTC_B], a[a["week"] >= score_mod.RTC_B]
    out.append(_table(pre, f"=== PRE-RTC+B (< {score_mod.RTC_B.date()}) ==="))
    out.append(_table(post, f"=== POST-RTC+B (≥ {score_mod.RTC_B.date()}) ==="))

    out.append("\n=== THE PRE-REGISTERED BARS (plan/s6-gate.md) ===")
    out.append(f"  existence test — beat persistence: top-decile > {PERSISTENCE_TOPDEC}")
    out.append(f"  product test (§5.5)             : top-decile ≥ {PRODUCT_TOPDEC}")
    out.append("  These are DIFFERENT questions. Persistence's own top-decile "
               f"({PERSISTENCE_TOPDEC}) is BELOW the product bar,")
    out.append("  so an arm can beat persistence, absorb it entirely, and still not "
               "ship a product.")

    # Attribution: what did each covariate family actually buy, over base?
    out.append("\n=== ATTRIBUTION (top-decile vs the `base` arm) ===")
    m = a[a["source"] == "model"]
    base_td = m[m["arm"] == "base"].topdecile_hit.mean()
    for arm in ARMS:
        td = m[m["arm"] == arm].topdecile_hit.mean()
        out.append(f"  {arm:<6} {td:>7.3f}   {td - base_td:+7.3f}")
    out.append("  If the answer is 'lagged μ, and the rest added nothing', say so "
               "plainly (gate, §attribution).")

    if bands is not None and not bands.empty:
        out.append("\n=== BANDS (coverage80; target 0.800) ===")
        for arm in ARMS:
            b = bands[bands["arm"] == arm]
            if not b.empty:
                out.append(f"  {arm:<6} coverage80 {b.coverage80.mean():.3f}   "
                           f"P50 R² {b.pooled_r2.mean():+.3f}")
        out.append("  0085 measured 0.673 — the sampler treats binding as independent "
                   "across constraints.\n  Out of scope here (plan/0088): a joint "
                   "sampler makes the bands honest, not skillful.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from compute.jobs import backfill_nodal
    from compute.mu.features import build_panel, net_load_regime, system_panel
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default="2025-08-14")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d")
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--preds-dir", default="/compute/mu/ablation")
    p.add_argument("--out", default="/compute/mu/ablation.csv")
    p.add_argument("--bands", action="store_true",
                   help="also propagate to nodal P10/P50/P90 and report coverage80")
    p.add_argument("--no-resume", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    arms = [a for a in args.arms.split(",") if a]
    unknown = set(arms) - set(FEATURE_SETS)
    if unknown:
        raise SystemExit(f"unknown arm(s): {sorted(unknown)}")

    preds_dir = Path(args.preds_dir)
    preds_dir.mkdir(parents=True, exist_ok=True)

    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    score_from = pd.Timestamp(args.score_from, tz="UTC")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    t0 = time.perf_counter()
    with psycopg.connect(dsn) as conn:
        log.info("loading panels %s → %s", lo.date(), hi.date())
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
        log.info("M = %s   C = %s", M.shape, C.shape)

        # ONE panel, every arm's columns. This is the load-bearing line of commit 5.
        panel = build_panel(conn, M, lo, hi, policy=args.policy, C=C,
                            score_from=score_from, with_weather=True)
        sysp = system_panel(conn, lo, hi)
        regimes = net_load_regime(sysp, fit_index=sysp.index)

    n_geo = len([c for c in panel.columns if c.startswith("geo_")])
    n_wx = len([c for c in panel.columns if c.startswith("wx_")])
    n_lag = len([c for c in panel.columns if c.startswith("lag_")])
    log.info("panel = %s rows × %d cols (%d lag, %d geo, %d wx), %.2f GB — built once",
             f"{len(panel):,}", panel.shape[1], n_lag, n_geo, n_wx,
             panel.memory_usage(deep=False).sum() / 1e9)
    if not (n_lag and n_geo and n_wx):
        raise SystemExit("an arm has no columns — the panel is not the ablation panel")

    anchor = M.index[0].normalize()
    rows, band_rows = [], []
    for arm in arms:
        preds = run_arm(panel, arm, preds_dir / f"preds_{arm}.npz",
                        args.train_days, args.refit_days, score_from, anchor,
                        resume=not args.no_resume)

        log.info("arm %-5s: scoring through the UNCHANGED 0085 harness", arm)
        df = score_mod.walk(M, C, preds, regimes)
        df["arm"] = arm
        rows.append(df)

        if args.bands:
            b = backfill_nodal.walk(M, C, preds)
            b["arm"] = arm
            band_rows.append(b)

    out = pd.concat(rows, ignore_index=True)
    check_baselines_identical(out)

    bands = pd.concat(band_rows, ignore_index=True) if band_rows else None
    print(report(out, bands))

    out.to_csv(args.out, index=False)
    print(f"\nwrote {args.out}")
    if bands is not None:
        bands_path = args.out.replace(".csv", "_bands.csv")
        bands.to_csv(bands_path, index=False)
        print(f"wrote {bands_path}")
    log.info("total %.0f min", (time.perf_counter() - t0) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
