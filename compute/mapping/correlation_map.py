"""
CM.1 — correlation map.

Maps each ERCOT SP to its most-correlated model bus over shared hours.

Model and ERCOT sides use different reference-price methods that target
the same conceptual quantity (system marginal energy):
  * model:  `system_lambda_merit_order` (merit-order stack, ~$29 stable)
  * ercot:  `system_lambda` (ERCOT-published system lambda)
Values are expected to track but not equal.

Reads `runs/<run_id>/matrix/congestion_matrices.npz` (produced by
`compute.matrix`) and — in later sections — writes:

  * `runs/<run_id>/mapping/mapping_correlation_<run_id>.parquet`
  * `runs/<run_id>/mapping/mapping_correlation_summary_<run_id>.json`

Usage:
    python -m compute.mapping.correlation_map --run-id v1-120 \
        [--model-ref system_lambda_merit_order] \
        [--ercot-ref system_lambda] \
        [--var-threshold 1.0] [--topk 5] [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = BASE_DIR / "runs"

DEFAULT_MODEL_REF = "system_lambda_merit_order"
DEFAULT_ERCOT_REF = "system_lambda"


def _matrix_npz_path(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "matrix" / "congestion_matrices.npz"


def load_matrices(
    run_id: str,
    model_ref: str = DEFAULT_MODEL_REF,
    ercot_ref: str = DEFAULT_ERCOT_REF,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load model and ERCOT congestion matrices under (possibly different)
    reference methods and align them on their shared hour axis.

    The model side (`system_lambda_merit_order`) and the ERCOT side
    (`system_lambda`) target the same conceptual reference (system
    marginal energy) but are computed from different sources, so keys
    diverge in the npz.

    Returns (model_C, ercot_C, bus_ids, sp_ids, hours) where matrices are
    (n_bus, n_hours) and (n_sp, n_hours) aligned to the same `hours`.
    """
    path = _matrix_npz_path(run_id)
    if not path.exists():
        raise SystemExit(f"matrix file not found: {path}")

    with np.load(path) as z:
        keys = {
            "model_C": f"{model_ref}_model_C",
            "ercot_C": f"{ercot_ref}_ercot_C",
            "bus_ids": f"{model_ref}_model_bus_ids",
            "sp_ids": f"{ercot_ref}_ercot_sp_ids",
            "model_hours": f"{model_ref}_model_hours",
            "ercot_hours": f"{ercot_ref}_ercot_hours",
        }
        missing = [k for k in keys.values() if k not in z.files]
        if missing:
            raise SystemExit(
                f"missing arrays in {path}: {missing} "
                f"(model_ref={model_ref}, ercot_ref={ercot_ref})"
            )
        model_C = z[keys["model_C"]]
        ercot_C = z[keys["ercot_C"]]
        bus_ids = z[keys["bus_ids"]]
        sp_ids = z[keys["sp_ids"]]
        model_hours = z[keys["model_hours"]]
        ercot_hours = z[keys["ercot_hours"]]

    if model_hours.size == 0 or ercot_hours.size == 0:
        # No shared axis: hand back empty aligned arrays so callers can
        # detect and surface the condition rather than crash on shape.
        hours = np.empty((0,), dtype=str)
        return (
            np.empty((model_C.shape[0], 0), dtype=float),
            np.empty((ercot_C.shape[0], 0), dtype=float),
            bus_ids, sp_ids, hours,
        )

    if np.array_equal(model_hours, ercot_hours):
        return model_C, ercot_C, bus_ids, sp_ids, model_hours

    # Intersect while preserving model-side order.
    ercot_set = {h: i for i, h in enumerate(ercot_hours.tolist())}
    shared: list[str] = []
    m_idx: list[int] = []
    e_idx: list[int] = []
    for i, h in enumerate(model_hours.tolist()):
        j = ercot_set.get(h)
        if j is None:
            continue
        shared.append(h)
        m_idx.append(i)
        e_idx.append(j)
    hours = np.array(shared, dtype=str)
    model_aligned = model_C[:, m_idx] if m_idx else np.empty(
        (model_C.shape[0], 0), dtype=float,
    )
    ercot_aligned = ercot_C[:, e_idx] if e_idx else np.empty(
        (ercot_C.shape[0], 0), dtype=float,
    )
    return model_aligned, ercot_aligned, bus_ids, sp_ids, hours


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Correlate ERCOT SPs to model buses over shared hours.",
    )
    ap.add_argument("--run-id", required=True,
                    help="Run identifier under compute/runs/.")
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF,
                    help=f"Model-side reference method (default {DEFAULT_MODEL_REF}).")
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF,
                    help=f"ERCOT-side reference method (default {DEFAULT_ERCOT_REF}).")
    ap.add_argument("--var-threshold", type=float, default=1.0,
                    help="Drop rows with std < threshold ($/MWh, default 1.0).")
    ap.add_argument("--topk", type=int, default=5,
                    help="Top-k buses to record per SP (default 5).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load matrices and print shapes, then exit.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    model_C, ercot_C, bus_ids, sp_ids, hours = load_matrices(
        args.run_id, model_ref=args.model_ref, ercot_ref=args.ercot_ref,
    )
    print(f"run_id={args.run_id} model_ref={args.model_ref} "
          f"ercot_ref={args.ercot_ref}")
    print(f"model_C shape={model_C.shape} (bus x hour)")
    print(f"ercot_C shape={ercot_C.shape} (sp x hour)")
    print(f"bus_ids={bus_ids.shape[0]} sp_ids={sp_ids.shape[0]} hours={hours.shape[0]}")

    if args.dry_run:
        return

    # ------------------------------------------------------------------
    # CORRELATION CORE — bus↔SP Pearson matrix over shared hours goes here.
    # Pipeline: load_matrices → prefilter_low_variance
    #        → correlate(model_C, ercot_C)  ← R[bus, sp] built here (C2)
    #        → select_best_and_topk         ← argmax per SP + top-k (C2)
    #        → write parquet + summary JSON (C3)
    # ------------------------------------------------------------------
    raise SystemExit("correlation core not implemented yet (C2/C3 pending)")


if __name__ == "__main__":
    main()
