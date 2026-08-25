"""R3 verdict: does collinear grouping buy refit stability, and at what cost?

Reads the per-week rows emitted by ``sweep_sf --per-week-out`` and scores each
grouped arm against the **pre-registered bars** in plan/0083 — which were fixed
before the numbers were seen and are not to be edited after (handoff §10).

  Pass (stability): sf_stability rises >= +0.10 over sf_stability_proj — the
    ungrouped SF projected into the SAME group row-space. Not over the raw
    ungrouped SF: a grouped matrix has fewer, better-conditioned rows and would
    look steadier for that reason alone, which would be a measurement artifact
    rather than a finding.
  Guard (accuracy): rank_spearman / sign_agree / topdecile_hit each within 0.01
    of the ungrouped arm, and oos_pooled_r2 within 0.02. Grouping may not buy
    stability by destroying locality.

Everything is also split pre/post the RTC+B cutover (2025-12-05): DAM virtual AS
can move the mu patterns, so a number pooled across it hides a regime change.

    docker compose run --rm compute python -m compute.experiments.sf.grouping_verdict \\
      --per-week /compute/runs/experiments/sf/sf_sweep_grouping_weekly.csv
"""
from __future__ import annotations

import argparse

import pandas as pd

RTCB_CUTOVER = pd.Timestamp("2025-12-05", tz="UTC")

STABILITY_BAR = 0.10          # absolute rise over the projected control
GUARD_SCREENING = 0.01        # spearman / sign / top-decile
GUARD_R2 = 0.02               # pooled R2

SCREENING = ["rank_spearman", "sign_agree", "topdecile_hit"]


def _mean(df: pd.DataFrame, col: str) -> float:
    return float(df[col].mean()) if col in df else float("nan")


def verdict(weekly: pd.DataFrame) -> pd.DataFrame:
    base = weekly[weekly["rho_min"] == "ungrouped"]
    if base.empty:
        raise SystemExit("no ungrouped arm in the per-week rows — sweep with "
                         "`--rho-min none,...` so the baseline comes from the "
                         "same weeks and panels")

    rows = []
    for rho, arm in weekly[weekly["rho_min"] != "ungrouped"].groupby("rho_min"):
        stab = _mean(arm, "sf_stability")
        proj = _mean(arm, "sf_stability_proj")
        delta = stab - proj
        guards = {m: _mean(arm, m) - _mean(base, m) for m in SCREENING}
        d_r2 = _mean(arm, "oos_pooled_r2") - _mean(base, "oos_pooled_r2")

        guard_ok = (all(v >= -GUARD_SCREENING for v in guards.values())
                    and d_r2 >= -GUARD_R2)
        rows.append({
            "rho_min": rho,
            "n_groups": _mean(arm, "n_groups"),
            "n_constraints": _mean(arm, "n_constraints"),
            "compression": _mean(arm, "n_constraints") / max(_mean(arm, "n_groups"), 1),
            "group_churn": _mean(arm, "group_churn"),
            "stability": stab,
            "control": proj,
            "delta": delta,
            "d_oos_r2": d_r2,
            **{f"d_{m}": v for m, v in guards.items()},
            "PASS_stability": delta >= STABILITY_BAR,
            "PASS_guard": guard_ok,
        })
    return pd.DataFrame(rows).sort_values("rho_min")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--per-week", required=True)
    args = p.parse_args(argv)

    weekly = pd.read_csv(args.per_week, parse_dates=["score_start"])
    if weekly["score_start"].dt.tz is None:
        weekly["score_start"] = weekly["score_start"].dt.tz_localize("UTC")

    pd.set_option("display.width", 240)
    fmt = lambda v: f"{v:.3f}"  # noqa: E731

    splits = [
        ("ALL", weekly),
        ("PRE-RTC+B", weekly[weekly["score_start"] < RTCB_CUTOVER]),
        ("POST-RTC+B", weekly[weekly["score_start"] >= RTCB_CUTOVER]),
    ]
    for name, part in splits:
        if part.empty:
            continue
        n_weeks = part[part["rho_min"] == "ungrouped"]["score_start"].nunique()
        print(f"\n=== {name} — {n_weeks} scored weeks ===")
        print(verdict(part).to_string(index=False, float_format=fmt))

    v = verdict(weekly)
    passed = v[v["PASS_stability"] & v["PASS_guard"]]
    print(f"\n{'=' * 70}")
    print(f"PRE-REGISTERED BARS: stability delta >= +{STABILITY_BAR:.2f} over the "
          f"projected control;\n  screening within {GUARD_SCREENING:.2f} and "
          f"pooled R2 within {GUARD_R2:.2f} of ungrouped.")
    if passed.empty:
        best = v.loc[v["delta"].idxmax()]
        print(f"\nR3 = FAIL. Best arm rho_min={best.rho_min}: stability "
              f"{best.stability:.3f} vs control {best.control:.3f} "
              f"= {best.delta:+.3f}, short of +{STABILITY_BAR:.2f}.")
        print("  Grouping does NOT ship as the fit unit; signed per-group "
              "claims and the node explorer stay blocked.")
    else:
        print(f"\nR3 = PASS at rho_min ∈ {sorted(passed['rho_min'])}.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
