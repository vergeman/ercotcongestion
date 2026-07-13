"""Regime-conditioned scorecard diagnostic — CLI driver.

Reads the existing matrix + partition artifacts, buckets hours by one
or more regime schemes, and reports per-bucket + pooled scorecard
metrics side by side. Pooled row is asserted to match the previously
promoted scorecard headline (when that file exists) so we know we're
comparing apples to apples.

Step 1 of plan/handoff-regime.md. Diagnostic only — nothing under
``runs/<run>/mapping/`` is touched; outputs land in
``runs/<run>/experiments/regime_scorecard/``.

Usage:
    python -m compute.legacy.experiments.regime_scorecard.run \
        --run-id v1-annual \
        --bins congestion_magnitude:q4,net_load:q4,binding_active \
        --ref kkt_perbus \
        --model-ref kkt_perbus \
        --ercot-ref zone_local_spp \
        --algo hierarchical_on_beta \
        --k 6
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np

from compute.legacy.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    RUNS_ROOT,
    load_matrices,
)
from compute.legacy.mapping.scorecard import (
    DEFAULT_ALGO,
    DEFAULT_DEADBAND,
    DEFAULT_K,
    DEFAULT_MIN_MEMBERS,
    aggregate,
    load_partition,
    score,
)
from compute.legacy.regimes import BinResult, bin_hours, load_hourly_covariates
from compute.legacy.regimes.binners import parse_scheme

logger = logging.getLogger(__name__)

DEFAULT_BINS = "congestion_magnitude:q4,net_load:q4,binding_active"
DEFAULT_MIN_BUCKET_HOURS = 24
POOLED_HEADLINE_TOLERANCE = 1e-9


def _experiments_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "experiments" / "regime_scorecard"


def _scorecard_json_path(
    run_id: str, ref: str, algo: str, k: int,
) -> Path:
    cell = f"{run_id}_{ref}_{algo}_k{int(k)}"
    return RUNS_ROOT / run_id / "mapping" / f"scorecard_{cell}.json"


def _scheme_slug(scheme: str) -> str:
    """Filesystem-safe tag for a scheme string."""
    return scheme.replace(":", "_")


def _needs_covariates(schemes: list[str]) -> bool:
    for s in schemes:
        driver, _ = parse_scheme(s)
        if driver == "net_load":
            return True
    return False


def _score_bucket(
    model_Z: np.ndarray,
    ercot_Z: np.ndarray,
    mask: np.ndarray,
    deadband: float,
) -> dict:
    """Run ``scorecard.score`` on the mask-selected hour slice."""
    m = model_Z[mask]
    e = ercot_Z[mask]
    _corr, _sign, _spear, headline = score(m, e, deadband)
    return headline


def _bucket_hours(hours: np.ndarray, mask: np.ndarray) -> list[str]:
    return [str(h) for h in hours[mask].tolist()]


def _compare_pooled(
    pooled: dict, run_id: str, ref: str, algo: str, k: int,
) -> list[str]:
    """Compare pooled headline to the promoted scorecard file for the
    same ``(ref, algo, k)``. Returns any drift messages (empty when
    they match or the file is absent).

    Kept as a warning rather than a hard fail: the point of this
    diagnostic is the per-bucket table. A drift here means the current
    mapping/clustering artifacts on disk no longer reproduce the
    promoted scorecard — a data-consistency issue for the user to
    reconcile (rerun ``compute.legacy.mapping.scorecard`` or re-promote), not
    a defect in the diagnostic itself.
    """
    path = _scorecard_json_path(run_id, ref, algo, k)
    if not path.exists():
        logger.warning(
            "no existing scorecard at %s — skipping pooled sanity check",
            path,
        )
        return []
    with open(path) as f:
        existing = json.load(f).get("headline", {})
    drift: list[str] = []
    for key in ("zone_rank_spearman_per_hour", "mean_corr", "mean_sign_agreement"):
        a = pooled.get(key)
        b = existing.get(key)
        if a is None or b is None:
            if a != b:
                drift.append(
                    f"pooled/{key} drift: diagnostic={a!r} promoted={b!r}"
                )
            continue
        if not math.isclose(a, b, rel_tol=1e-6, abs_tol=POOLED_HEADLINE_TOLERANCE):
            drift.append(
                f"pooled/{key} drift: diagnostic={a:.6f} promoted={b:.6f} "
                f"(delta={a - b:+.4f})"
            )
    if drift:
        logger.warning(
            "pooled row diverges from promoted scorecard at %s; the current "
            "mapping/clustering artifacts don't reproduce the promoted "
            "headline. Rerun compute.legacy.mapping.scorecard (or re-promote) to "
            "reconcile. Diagnostic per-bucket rows are still valid against "
            "the current artifacts.", path.name,
        )
        for msg in drift:
            logger.warning("  %s", msg)
    else:
        logger.info("pooled headline matches %s", path.name)
    return drift


def _build_buckets(
    result: BinResult,
    hours: np.ndarray,
    model_Z: np.ndarray,
    ercot_Z: np.ndarray,
    deadband: float,
    min_bucket_hours: int,
) -> tuple[list[dict], list[str]]:
    buckets: list[dict] = []
    warnings: list[str] = []
    for bucket_id in range(result.n_buckets):
        mask = result.labels == bucket_id
        n_hours = int(mask.sum())
        row: dict[str, object] = {
            "id": int(bucket_id),
            "label": result.bucket_labels[bucket_id],
            "n_hours": n_hours,
            "hours": _bucket_hours(hours, mask),
        }
        if result.edges is not None:
            lo = float(result.edges[bucket_id])
            hi = float(result.edges[bucket_id + 1])
            row["range"] = [lo, hi]
        if n_hours < min_bucket_hours:
            warnings.append(
                f"bucket {result.bucket_labels[bucket_id]!r} has "
                f"{n_hours} hours (< {min_bucket_hours}); metrics skipped"
            )
            row["zone_rank_spearman_per_hour"] = None
            row["mean_corr"] = None
            row["mean_sign_agreement"] = None
        else:
            headline = _score_bucket(model_Z, ercot_Z, mask, deadband)
            row["zone_rank_spearman_per_hour"] = headline["zone_rank_spearman_per_hour"]
            row["mean_corr"] = headline["mean_corr"]
            row["mean_sign_agreement"] = headline["mean_sign_agreement"]
        buckets.append(row)
    n_unassigned = int((result.labels == -1).sum())
    if n_unassigned:
        warnings.append(
            f"{n_unassigned} hours had NaN driver and were excluded"
        )
    return buckets, warnings


def _write_output(
    run_id: str,
    scheme: str,
    ref: str,
    model_ref: str,
    ercot_ref: str,
    algo: str,
    k: int,
    deadband: float,
    min_members: int,
    min_bucket_hours: int,
    result: BinResult,
    buckets: list[dict],
    pooled: dict,
    covariate_missing: list[str],
    warnings: list[str],
) -> Path:
    out_dir = _experiments_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    cell = f"{run_id}_{ref}_{algo}_k{int(k)}"
    filename = f"{cell}_{_scheme_slug(scheme)}.json"
    path = out_dir / filename

    pooled_row = {
        "id": None,
        "label": "pooled",
        "n_hours": pooled.get("n_hours"),
        "hours": None,
        "zone_rank_spearman_per_hour": pooled.get("zone_rank_spearman_per_hour"),
        "mean_corr": pooled.get("mean_corr"),
        "mean_sign_agreement": pooled.get("mean_sign_agreement"),
    }

    payload = {
        "run_id": run_id,
        "params": {
            "ref": ref,
            "model_ref": model_ref,
            "ercot_ref": ercot_ref,
            "algo": algo,
            "k": int(k),
            "bins": scheme,
            "deadband": float(deadband),
            "min_members": int(min_members),
            "min_bucket_hours": int(min_bucket_hours),
        },
        "scheme_meta": {
            "driver": result.driver_name,
            "n_buckets": result.n_buckets,
            "edges": (
                [float(x) for x in result.edges.tolist()]
                if result.edges is not None else None
            ),
            "bucket_labels": list(result.bucket_labels),
            "covariate_missing": covariate_missing,
        },
        "buckets": [*buckets, pooled_row],
        "warnings": warnings,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def _print_table(scheme: str, buckets: list[dict], pooled: dict) -> None:
    print(f"\n=== {scheme} ===")
    print(f"{'bucket':>10} {'n_hours':>8} {'rank_sp':>10} {'mean_corr':>10} {'sign_agr':>10}")
    for b in buckets:
        rs = _fmt(b.get("zone_rank_spearman_per_hour"))
        mc = _fmt(b.get("mean_corr"))
        sa = _fmt(b.get("mean_sign_agreement"))
        print(f"{b['label']:>10} {b['n_hours']:>8} {rs:>10} {mc:>10} {sa:>10}")
    rs = _fmt(pooled.get("zone_rank_spearman_per_hour"))
    mc = _fmt(pooled.get("mean_corr"))
    sa = _fmt(pooled.get("mean_sign_agreement"))
    print(f"{'pooled':>10} {pooled.get('n_hours', 0):>8} {rs:>10} {mc:>10} {sa:>10}")


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Regime-conditioned scorecard diagnostic. "
            "Reports per-bucket + pooled scorecard metrics for one or "
            "more regime bin schemes."
        ),
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument(
        "--bins",
        default=DEFAULT_BINS,
        help=(
            "Comma-separated bin schemes. Supported: "
            "congestion_magnitude:qN, net_load:qN, binding_active. "
            f"Default: {DEFAULT_BINS}"
        ),
    )
    ap.add_argument("--ref", default=DEFAULT_MODEL_REF)
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF)
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF)
    ap.add_argument("--algo", default=DEFAULT_ALGO)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--deadband", type=float, default=DEFAULT_DEADBAND)
    ap.add_argument("--min-members", type=int, default=DEFAULT_MIN_MEMBERS)
    ap.add_argument(
        "--min-bucket-hours", type=int, default=DEFAULT_MIN_BUCKET_HOURS,
        help=(
            "Skip metric computation for buckets with fewer hours than "
            f"this (default {DEFAULT_MIN_BUCKET_HOURS})."
        ),
    )
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s",
    )

    schemes = [s.strip() for s in args.bins.split(",") if s.strip()]
    for s in schemes:
        parse_scheme(s)  # early validation

    model_C, ercot_C, bus_ids, sp_ids, hours = load_matrices(
        args.run_id, model_ref=args.model_ref, ercot_ref=args.ercot_ref,
    )
    print(
        f"run_id={args.run_id} model_ref={args.model_ref} "
        f"ercot_ref={args.ercot_ref} algo={args.algo} k={args.k}"
    )
    print(
        f"model_C={model_C.shape} ercot_C={ercot_C.shape} "
        f"hours={hours.shape[0]}"
    )

    bus_to_cluster, sp_to_cluster = load_partition(
        args.run_id, args.ref, args.algo, args.k,
    )
    cluster_ids, model_Z, ercot_Z, _n_buses, _n_sps, agg_warnings = aggregate(
        model_C, ercot_C, bus_ids, sp_ids,
        bus_to_cluster, sp_to_cluster,
        args.min_members,
    )
    print(f"kept zones: {cluster_ids.tolist()}")
    for w in agg_warnings:
        print(f"  agg warn: {w}")

    _corr, _sign, _spear, pooled = score(model_Z, ercot_Z, args.deadband)
    pooled_drift = _compare_pooled(
        pooled, args.run_id, args.ref, args.algo, args.k,
    )

    covariates: dict[str, np.ndarray] | None = None
    covariate_missing: list[str] = []
    if _needs_covariates(schemes):
        logger.info("loading ERCOT covariates from Postgres…")
        covariates, covariate_missing = load_hourly_covariates(hours)
        if covariate_missing:
            logger.warning(
                "missing covariates: %s — schemes requiring them will fail",
                covariate_missing,
            )

    written: list[Path] = []
    for scheme in schemes:
        try:
            result = bin_hours(
                scheme,
                hours=hours,
                model_C=model_C,
                ercot_C=ercot_C,
                covariates=covariates,
            )
        except ValueError as e:
            logger.error("scheme %r skipped: %s", scheme, e)
            continue

        buckets, scheme_warnings = _build_buckets(
            result, hours, model_Z, ercot_Z,
            args.deadband, args.min_bucket_hours,
        )

        path = _write_output(
            run_id=args.run_id,
            scheme=scheme,
            ref=args.ref,
            model_ref=args.model_ref,
            ercot_ref=args.ercot_ref,
            algo=args.algo,
            k=args.k,
            deadband=args.deadband,
            min_members=args.min_members,
            min_bucket_hours=args.min_bucket_hours,
            result=result,
            buckets=buckets,
            pooled=pooled,
            covariate_missing=covariate_missing,
            warnings=[*agg_warnings, *scheme_warnings, *pooled_drift],
        )
        _print_table(scheme, buckets, pooled)
        written.append(path)
        print(f"wrote {path}")

    if not written:
        raise SystemExit("no schemes produced output")


if __name__ == "__main__":
    main()
