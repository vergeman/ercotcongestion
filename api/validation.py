"""GET /api/validation — zone-aggregated scorecard.

Serves the artifact ``compute.mapping.scorecard`` writes for whichever
cell is currently promoted:

  * ``<served_run_dir>/mapping/scorecard.json``       (symlink)
  * ``<served_run_dir>/mapping/scorecard_series.npz`` (symlink)

``served_run_dir`` is itself a symlink managed by ``compute.promote``,
and the two files inside the run point at the per-cell realisations. The
endpoint takes no query params — swapping cells is a filesystem op, not
a request-time choice — and every scoring parameter (deadband,
min_members, ref, algo, k) is read from the JSON's own ``params`` field.

A missing symlink target returns 503: the correct fix is to promote a
run, not to reshape the request.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from models import (
    ScorecardHeadline,
    ScorecardParams,
    ScorecardResponse,
    ScorecardSeries,
    ScorecardZone,
)
from shared.settings import settings

router = APIRouter()


def _mapping_dir() -> Path:
    return Path(settings.served_run_dir) / "mapping"


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
    summary="Per-zone scorecard for the currently-served cell (model vs ERCOT by derived zone)",
)
def get_validation() -> ScorecardResponse:
    mdir = _mapping_dir()
    json_path = mdir / "scorecard.json"
    npz_path = mdir / "scorecard_series.npz"

    if not json_path.exists() or not npz_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"no scorecard is currently served. "
                f"Promote a run: python -m compute.promote "
                f"--run-id <id> --ref <ref> --algo <algo> --k <k>."
            ),
        )

    with open(json_path) as f:
        payload = json.load(f)

    return ScorecardResponse(
        run_id=payload["run_id"],
        params=ScorecardParams(**payload["params"]),
        headline=ScorecardHeadline(**payload["headline"]),
        zones=[ScorecardZone(**z) for z in payload["zones"]],
        series=_load_series(npz_path),
        warnings=payload.get("warnings", []),
    )
