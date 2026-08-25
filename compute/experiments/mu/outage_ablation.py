"""The generation-outage ablation — marginal value over 0088. plan/0089 commit 4.

**0088's five arms are pre-registered and frozen (`plan/s6-gate.md`); this arm was not
among them, so it is not retro-added there.** Instead it is measured *marginally*, on the
same panel and the same harness, and this file is a thin driver over 0088's machinery
rather than a second one:

  * the panel is built **once** here with `with_outage=True` (and every 0088 arm's columns
    present), and each arm is a column mask over that one object — `run_arm` and
    `check_baselines_identical` is imported from `feature_ablation` unchanged, and
    scoring goes through **`compute.evaluation.mu`, unimported-around**. There is exactly
    one scoring harness in this package and 0089 does not get to write a second one;
  * the four rows are **`base` / `all` / `out` / `all+out`**. `out` is `base` plus the
    per-constraint outage exposure; `all+out` is 0088's `all` plus it.

**The zonal fallback is `base`, and that is the row `out` must beat.** `features.outage_panel`
already hands every arm the R4 zonal aggregate — four load-zone MW numbers, *identical for
every constraint in an hour* — as unprefixed base features. So `base` already contains the
zonal outage signal, and `out − base` is precisely the lift of going **per-constraint** over
that aggregate. If it is not positive, the arm degrades to the fallback R4 already gave us,
and commit 5 says so plainly (plan/0089).

Walk-only by default (build the panel, save each arm's preds npz, memory-frugal); pass
`--score` for the assembly pass that scores the cached npz and writes the CSV + verdict.
`run_outage_ablation.sh` drives the per-arm walks then one `--score` pass.

    docker compose run --rm compute python -m compute.experiments.mu.outage_ablation \
      --score-from 2025-08-14 --score --out /compute/runs/experiments/mu/outage_ablation.csv
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pandas as pd

from compute.evaluation import mu as score_mod
from compute.experiments.mu.feature_ablation import (
    PERSISTENCE_TOPDEC, PRODUCT_TOPDEC, _row, check_baselines_identical, run_arm,
)
from compute.mu_forecast.model.runner import (DEFAULT_REFIT_DAYS, DEFAULT_TRAIN_DAYS,
                                 FEATURE_SETS, feature_cols)

log = logging.getLogger("compute.experiments.mu.outage_ablation")

# base is the zonal fallback (outages_zonal ⊂ base); out/all+out are the arm under test.
ARMS = ["base", "all", "out", "all+out"]


def _table(df: pd.DataFrame, title: str) -> str:
    out = [f"\n{title}",
           f"  {'arm':<16} {'R2':>7} {'MAE':>8} {'Spearman':>9} {'sign':>7} "
           f"{'top-dec':>8}   verdict"]
    labels = {"base": "base (zonal)", "out": "out (percon)"}
    for arm in ARMS:
        out.append(_row(df[(df["arm"] == arm) & (df["source"] == "model")],
                        f"model:{labels.get(arm, arm)}"))
    out.append("  " + "-" * 62)
    one = df[df["arm"] == ARMS[0]]
    for src in ("persistence", "climatology", "oracle"):
        out.append(_row(one[one["source"] == src], src))
    return "\n".join(out)


def report(df: pd.DataFrame) -> str:
    a = df[df["regime"] == "all"]
    out = [_table(a, "=== OUTAGE ABLATION: ALL WEEKS ===")]

    pre, post = a[a["week"] < score_mod.RTC_B], a[a["week"] >= score_mod.RTC_B]
    out.append(_table(pre, f"=== PRE-RTC+B (< {score_mod.RTC_B.date()}) ==="))
    out.append(_table(post, f"=== POST-RTC+B (≥ {score_mod.RTC_B.date()}) ==="))

    out.append("\n=== THE PRE-REGISTERED BARS (plan/s6-gate.md) ===")
    out.append(f"  existence — beat persistence: top-decile > {PERSISTENCE_TOPDEC}")
    out.append(f"  product (§5.5)              : top-decile ≥ {PRODUCT_TOPDEC}")

    # The verdict this whole arm turns on: per-constraint exposure vs the zonal
    # aggregate that base already carries. `base` IS the zonal fallback.
    m = a[a["source"] == "model"]
    def td(arm: str) -> float:
        return float(m[m["arm"] == arm].topdecile_hit.mean())
    out.append("\n=== DOES PER-CONSTRAINT OUTAGE EXPOSURE BEAT THE ZONAL FALLBACK? ===")
    out.append("  base IS the zonal fallback (outages_zonal is an unprefixed base "
               "feature, present in every arm).")
    out.append(f"  {'out  − base (over zonal, alone)':<34} {td('out') - td('base'):+7.3f}")
    out.append(f"  {'all+out − all (over zonal, on top of all)':<34} "
               f"{td('all+out') - td('all'):+7.3f}")
    out.append("  A positive delta is per-constraint lift OVER the zonal aggregate; "
               "≤0 degrades to R4's fallback (commit 5 states it either way).")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from compute.mu_forecast.panel.build import build_panel, net_load_regime, system_panel
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default="2025-08-14")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d")
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--preds-dir", default="/compute/runs/experiments/mu/outage_ablation")
    p.add_argument("--out", default="/compute/runs/experiments/mu/outage_ablation.csv")
    p.add_argument("--no-resume", action="store_true")
    # Walk-only is the DEFAULT: build the panel, run each arm's walk, save its preds
    # npz, then stop — freeing M/C/regimes first (the walk reads only the panel) so
    # the memory-heavy fit clears a small node; the `all` arm's first fold otherwise
    # peaks right at this node's RAM. `--score` opts into the assembly pass — reuse
    # the cached npz, score every arm through the 0085 harness, write the CSV +
    # verdict. Scoring holds M/C but does no heavy fit, so it is safe once at the end.
    p.add_argument("--score", dest="walk_only", action="store_false",
                   help="score the cached preds and write the CSV/verdict (the "
                        "assembly pass). Default is walk-only — save npz and stop.")
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

        # ONE panel, every arm's columns — 0088's plus the outage exposure. The arm
        # is a column mask over this object; it is never rebuilt per arm.
        panel = build_panel(conn, M, lo, hi, policy=args.policy, C=C,
                            score_from=score_from, with_weather=True,
                            with_outage=True)
        sysp = system_panel(conn, lo, hi)
        regimes = net_load_regime(sysp, fit_index=sysp.index)

    n_out = len([c for c in panel.columns if c.startswith("out_")])
    log.info("panel = %s rows × %d cols (%d outage-exposure) — built once",
             f"{len(panel):,}", panel.shape[1], n_out)
    if not n_out:
        raise SystemExit("no out_ columns — resource_outages is empty or the crosswalk "
                         "placed nothing; the ablation cannot measure the arm")

    anchor = M.index[0].normalize()

    if args.walk_only:
        # Per-arm isolated pass. The walk reads only `panel`; M/C/sysp/regimes are
        # scoring inputs held for the loop below. Free them here so the heavy fit
        # (the `all` arm's first fold peaks near this node's RAM) has ~1 GB more to
        # breathe. The npz is the whole product of this mode — the assembly pass
        # (no --walk-only) reloads M/C and scores from these cached npz.
        import gc
        del M, C, sysp, regimes
        gc.collect()
        for arm in arms:
            run_arm(panel, arm, preds_dir / f"preds_{arm.replace('+', '_')}.npz",
                    args.train_days, args.refit_days, score_from, anchor,
                    resume=not args.no_resume)
            log.info("arm %-8s: preds saved (walk-only)", arm)
        log.info("walk-only: %d arm(s) done, %.0f min", len(arms),
                 (time.perf_counter() - t0) / 60)
        return 0

    rows = []
    for arm in arms:
        preds = run_arm(panel, arm, preds_dir / f"preds_{arm.replace('+', '_')}.npz",
                        args.train_days, args.refit_days, score_from, anchor,
                        resume=not args.no_resume)
        log.info("arm %-8s: %d features, scoring through the UNCHANGED 0085 harness",
                 arm, len(feature_cols(panel, FEATURE_SETS[arm])) + 1)
        df = score_mod.walk(M, C, preds, regimes)
        df["arm"] = arm
        rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    check_baselines_identical(out)
    print(report(out))

    out.to_csv(args.out, index=False)
    print(f"\nwrote {args.out}")
    log.info("total %.0f min", (time.perf_counter() - t0) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
