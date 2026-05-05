"""PTDF column lookup for the API.

The full PTDF matrix is large (~2700 lines × ~2750 buses) and topology-static.
We compute it once on first request and keep it in-memory. The endpoint
returns a single line's column, sparsified to entries above a small threshold
so the payload stays tight (a few hundred buses at most for any real line).
"""
from __future__ import annotations

import logging
import sys
from typing import Any

# /api is on sys.path via the topology_builder pattern; mirror it for compute.
sys.path.insert(0, '/compute')

import numpy as np

from config import NETWORK_NC

log = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "ptdf": None,         # np.ndarray, shape (n_branches, n_buses)
    "line_index": None,   # dict[str, int] — line_id → row index in ptdf
    "bus_names": None,    # list[str]
}


def _ensure_loaded() -> None:
    """Lazy-load the PTDF on first call. Cached for the lifetime of the process."""
    if _state["ptdf"] is not None:
        return

    import pypsa
    from ptdf_lodf import get_ptdf_lodf

    log.info("PTDF service: loading network from %s", NETWORK_NC)
    n = pypsa.Network(NETWORK_NC)
    ptdf, _lodf, bus_names = get_ptdf_lodf(n)

    # PTDF rows are stacked [lines, transformers] (see compute/fragility.py).
    # We only expose lines for hover; the API line_id space matches n.lines.
    line_ids = list(n.lines.index)
    line_index = {lid: i for i, lid in enumerate(line_ids)}

    _state["ptdf"] = ptdf
    _state["line_index"] = line_index
    _state["bus_names"] = bus_names
    log.info(
        "PTDF service: loaded ptdf shape=%s, %d lines, %d buses",
        ptdf.shape, len(line_index), len(bus_names),
    )


def get_line_ptdf_column(
    line_id: str,
    threshold: float = 1e-3,
    max_buses: int = 500,
) -> dict[str, Any] | None:
    """Return sparse PTDF column for a line.

    {
        "line_id": str,
        "buses": [{"bus_id": str, "ptdf": float}, ...],   # |ptdf| >= threshold
        "n_total_buses": int,                              # for context
        "n_returned": int,
    }

    Returns None if the line_id is unknown.
    """
    _ensure_loaded()
    line_index: dict[str, int] = _state["line_index"]
    if line_id not in line_index:
        return None

    ptdf: np.ndarray = _state["ptdf"]
    bus_names: list[str] = _state["bus_names"]
    row_idx = line_index[line_id]
    col = ptdf[row_idx]    # shape (n_buses,)

    # Sparsify by absolute threshold.
    mask = np.abs(col) >= threshold
    idxs = np.flatnonzero(mask)

    # Cap to max_buses by sorting descending by |ptdf|.
    if idxs.size > max_buses:
        order = np.argsort(-np.abs(col[idxs]))
        idxs = idxs[order[:max_buses]]

    buses = [
        {"bus_id": str(bus_names[i]), "ptdf": float(col[i])}
        for i in idxs
    ]
    return {
        "line_id": line_id,
        "buses": buses,
        "n_total_buses": int(len(bus_names)),
        "n_returned": int(len(buses)),
    }
