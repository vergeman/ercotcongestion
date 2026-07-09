"""Bin hours into regime buckets.

Each scheme maps `(hours, matrices, covariates)` to a per-hour integer
label in `[0, n_buckets)`, plus enough metadata (edges, pretty labels)
for the caller to describe the bucket in output.

Schemes supported:

* ``congestion_magnitude:qN`` — quantile on per-hour mean of
  ``|ercot_C|`` across SPs. Requires ``ercot_C``.
* ``net_load:qN`` — quantile on ``load − wind − solar``. Requires
  covariates.
* ``binding_active`` — binary: is any bus showing meaningful modeled
  congestion this hour? Proxy = ``max |model_C[:, t]| >
  binding_deadband``. Numerical noise means model_C is essentially
  never exactly zero, so a nonzero-count proxy would tag every hour;
  the deadband (default 1.0 $/MWh) filters that out. This is a proxy
  for OPF μ availability — the real "is any line binding" signal lives
  outside the matrix npz. Requires ``model_C``.

``qN`` is a generic percentile-cut spec: ``q2`` → median split, ``q4``
→ quartiles, etc. Bucket sizes are equal by construction (±1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_QN_RE = re.compile(r"^(?P<name>[a-z_]+):q(?P<n>\d+)$")

DEFAULT_BINDING_DEADBAND = 1.0


@dataclass(frozen=True)
class BinResult:
    """Per-hour bucket assignment plus bucket-level metadata.

    ``labels`` is length-``n_hours``, values in ``[0, n_buckets)`` or -1
    for hours that could not be assigned (e.g., NaN driver). ``edges``
    is the ordered cut-point list (length ``n_buckets + 1``) for quantile
    schemes; ``None`` for categorical schemes like ``binding_active``.
    """
    scheme: str
    driver_name: str
    labels: np.ndarray
    n_buckets: int
    edges: np.ndarray | None
    bucket_labels: list[str]


def parse_scheme(scheme: str) -> tuple[str, int | None]:
    """Return ``(driver_name, n_quantiles_or_None)`` for a scheme string.

    ``"net_load:q4"`` → ``("net_load", 4)``; ``"binding_active"`` →
    ``("binding_active", None)``. Raises ``ValueError`` for unrecognised
    forms.
    """
    if scheme == "binding_active":
        return "binding_active", None
    m = _QN_RE.match(scheme)
    if not m:
        raise ValueError(
            f"unrecognised bin scheme: {scheme!r} "
            f"(expected 'binding_active' or '<driver>:qN')"
        )
    n = int(m.group("n"))
    if n < 2:
        raise ValueError(f"qN must have N >= 2 (got {scheme!r})")
    return m.group("name"), n


def bin_hours(
    scheme: str,
    *,
    hours: np.ndarray,
    model_C: np.ndarray | None = None,
    ercot_C: np.ndarray | None = None,
    covariates: dict[str, np.ndarray] | None = None,
    binding_deadband: float = DEFAULT_BINDING_DEADBAND,
) -> BinResult:
    """Compute per-hour bucket assignments for ``scheme``.

    Callers pass whichever matrices/covariates are available; each
    scheme validates its own inputs and raises ``ValueError`` if a
    required source is missing or all-NaN.
    """
    n_hours = int(hours.shape[0])
    driver_name, n_q = parse_scheme(scheme)

    if driver_name == "binding_active":
        if model_C is None:
            raise ValueError("binding_active requires model_C")
        driver = _binding_active_driver(model_C, binding_deadband)
        labels = driver.astype(np.int64)
        bucket_labels = ["inactive", "active"]
        return BinResult(
            scheme=scheme,
            driver_name=driver_name,
            labels=labels,
            n_buckets=2,
            edges=None,
            bucket_labels=bucket_labels,
        )

    assert n_q is not None
    if driver_name == "congestion_magnitude":
        if ercot_C is None:
            raise ValueError("congestion_magnitude:qN requires ercot_C")
        driver = _congestion_magnitude_driver(ercot_C)
    elif driver_name == "net_load":
        if covariates is None:
            raise ValueError("net_load:qN requires covariates")
        driver = _net_load_driver(covariates)
    else:
        raise ValueError(f"unknown driver: {driver_name!r}")

    if driver.shape[0] != n_hours:
        raise ValueError(
            f"driver length {driver.shape[0]} != n_hours {n_hours} "
            f"for scheme {scheme!r}"
        )

    labels, edges = _qcut(driver, n_q)
    bucket_labels = [f"Q{i + 1}" for i in range(n_q)]
    return BinResult(
        scheme=scheme,
        driver_name=driver_name,
        labels=labels,
        n_buckets=n_q,
        edges=edges,
        bucket_labels=bucket_labels,
    )


def _congestion_magnitude_driver(ercot_C: np.ndarray) -> np.ndarray:
    """Per-hour mean of ``|ercot_C|`` across SPs, ignoring NaN."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(np.abs(ercot_C), axis=0)


def _net_load_driver(covariates: dict[str, np.ndarray]) -> np.ndarray:
    """load − wind − solar, per hour. NaN in any input propagates."""
    missing = [k for k in ("load", "wind", "solar") if k not in covariates]
    if missing:
        raise ValueError(f"net_load driver missing covariates: {missing}")
    load = np.asarray(covariates["load"], dtype=float)
    wind = np.asarray(covariates["wind"], dtype=float)
    solar = np.asarray(covariates["solar"], dtype=float)
    return load - wind - solar


def _binding_active_driver(
    model_C: np.ndarray, deadband: float,
) -> np.ndarray:
    """Per-hour 0/1: does any bus's |modeled congestion| exceed
    ``deadband`` ($/MWh)?

    Numerical noise means ``model_C`` is essentially never exactly zero
    even in fully slack hours, so a naive nonzero-count proxy tags
    every hour. Thresholding on the per-hour max separates hours with
    meaningful modeled dispersion from ones dominated by noise. NaN
    entries — which mark buses filtered out of a given ref, not missing
    data — are treated as zero.
    """
    finite = np.where(np.isfinite(model_C), np.abs(model_C), 0.0)
    return (finite.max(axis=0) > deadband).astype(np.int64)


def _qcut(driver: np.ndarray, n_q: int) -> tuple[np.ndarray, np.ndarray]:
    """Assign each element of ``driver`` to a quantile bucket in ``[0, n_q)``.

    NaN values get label -1. Cut points come from the finite subset via
    ``np.quantile`` at ``[1/n, 2/n, …, (n-1)/n]``. Ties are broken by
    ``np.searchsorted(side='right')``, so mass on a cut edge falls into
    the upper bucket — this matches pandas' ``qcut`` default when there
    are no duplicated cut points.

    Returns ``(labels, edges)`` where ``edges`` has length ``n_q + 1``
    with the driver min/max at the ends.
    """
    finite_mask = np.isfinite(driver)
    finite = driver[finite_mask]
    if finite.size == 0:
        edges = np.full(n_q + 1, np.nan)
        return np.full(driver.shape, -1, dtype=np.int64), edges
    qs = np.linspace(0.0, 1.0, n_q + 1)
    edges = np.quantile(finite, qs)
    # inner cut points only
    cuts = edges[1:-1]
    labels = np.full(driver.shape, -1, dtype=np.int64)
    idx = np.searchsorted(cuts, driver[finite_mask], side="right")
    idx = np.clip(idx, 0, n_q - 1).astype(np.int64)
    labels[finite_mask] = idx
    return labels, edges
