"""Unit tests for shared immutable SF+μ artifact serving helpers."""
from __future__ import annotations

from datetime import date

import pandas as pd

from compute.sf.project import SfMuArtifact
from services.sf_artifacts import SfArtifactCache, normalize_constraint_key


def _artifact(value: float) -> SfMuArtifact:
    return SfMuArtifact(
        SF=pd.DataFrame([[value]], index=["C|BASE"], columns=["SP"]),
        E_mu=pd.DataFrame([[value]], index=pd.to_datetime(["2026-07-01T00:00Z"]),
                          columns=["C|BASE"]),
    )


def test_normalize_constraint_key_trims_only_outer_whitespace():
    assert normalize_constraint_key("  C North  ", " BASE CASE ") == "C North|BASE CASE"


def test_cache_keys_include_both_run_and_delivery_day():
    cache = SfArtifactCache()
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    a, b, c = _artifact(1.0), _artifact(2.0), _artifact(3.0)
    cache.put(("run-a", d1), a)
    cache.put(("run-b", d1), b)
    cache.put(("run-a", d2), c)

    assert cache.get(("run-a", d1)) is a
    assert cache.get(("run-b", d1)) is b
    assert cache.get(("run-a", d2)) is c
