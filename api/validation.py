"""GET /api/validation — zone-aggregated scorecard.

Serves the artifact produced by `compute.mapping.scorecard`:

  * `runs/<run_id>/mapping/scorecard_<run_id>.json`     — headline + per-zone rows
  * `runs/<run_id>/mapping/scorecard_series_<run_id>.npz` — per-hour model_Z / ercot_Z

The endpoint reads these files off the shared runs volume (`/compute/runs`
in-container by default; overridable via `COMPUTE_RUNS_DIR`). Compute is
authoritative — scoring parameters (deadband, min_members, algo, k) are
frozen at artifact write time. This handler just reads and serializes.

If no artifact exists for the requested `(run_id, algo, k)`, returns 404
with a message pointing to the CLI command that produces it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from models import (
    ScorecardHeadline,
    ScorecardParams,
    ScorecardResponse,
    ScorecardSeries,
    ScorecardZone,
)

router = APIRouter()

DEFAULT_ALGO = "hierarchical_on_beta"
DEFAULT_K = 6
COMPUTE_RUNS_DIR = Path(os.environ.get("COMPUTE_RUNS_DIR", "/compute/runs"))


def _mapping_dir(run_id: str) -> Path:
    return COMPUTE_RUNS_DIR / run_id / "mapping"


def _load_series(npz_path: Path) -> ScorecardSeries:
    with np.load(npz_path) as z:
        return ScorecardSeries(
            hours=z["hours"].astype(str).tolist(),
            cluster_ids=z["cluster_ids"].astype(int).tolist(),
            model_Z=z["model_Z"].astype(float).tolist(),
            ercot_Z=z["ercot_Z"].astype(float).tolist(),
        )


@router.get(
    "/validation",
    response_model=ScorecardResponse,
    summary="Per-zone scorecard for a run (model vs ERCOT congestion by derived zone)",
)
def get_validation(
    run_id: str = Query(..., description="Run identifier under compute/runs/."),
    algo: str = Query(DEFAULT_ALGO, description="Clustering algorithm used for the partition."),
    k: int = Query(DEFAULT_K, ge=2, description="K in the partition selection."),
) -> ScorecardResponse:
    mdir = _mapping_dir(run_id)
    json_path = mdir / f"scorecard_{run_id}.json"
    npz_path = mdir / f"scorecard_series_{run_id}.npz"

    if not json_path.exists() or not npz_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"scorecard artifact missing for run_id={run_id}. "
                f"Run: python -m compute.mapping.scorecard --run-id {run_id} "
                f"--algo {algo} --k {k}"
            ),
        )

    with open(json_path) as f:
        payload = json.load(f)

    # Reject stale artifacts from a different (algo, k). The frontend can
    # then either re-request the correct params or trigger a re-run.
    params = payload.get("params", {})
    if params.get("algo") != algo or int(params.get("k", -1)) != k:
        raise HTTPException(
            status_code=404,
            detail=(
                f"scorecard exists but was generated with algo={params.get('algo')} "
                f"k={params.get('k')}; requested algo={algo} k={k}. "
                f"Re-run compute.mapping.scorecard with the desired params."
            ),
        )

    return ScorecardResponse(
        run_id=payload["run_id"],
        params=ScorecardParams(**payload["params"]),
        headline=ScorecardHeadline(**payload["headline"]),
        zones=[ScorecardZone(**z) for z in payload["zones"]],
        series=_load_series(npz_path),
        warnings=payload.get("warnings", []),
    )
