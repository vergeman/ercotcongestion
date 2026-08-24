"""R4 spike (plan/0085 commit 1).

The spike's whole risk is a **confusion between its two legs**: the constraint
side resolves to named stations at 0.976 of mu-mass, and that number is not the
R4 bar. Joining needs a counterparty, and no public transmission-outage feed
exists — so joinable mass is zero. These tests plant that trap and check the
code refuses it, plus the empty-string station bug the first SQL pass shipped.
"""
from __future__ import annotations

import pandas as pd
import pytest

from compute.probes.outage_join import (R4_BUILD_BAR, R4_FLAGGED_BAR, joinable_mass,
                                        name_localization, station_resolution, verdict)


@pytest.fixture
def keys() -> pd.DataFrame:
    """Four keys: two resolved and heavy, one BASE CASE (no stations), one thin.

    ``BASE|CASE`` is the real shape of the miss — ERCOT writes **empty strings**
    for stationless constraints, which ``load_constraint_stations`` maps to None.
    A ``NOT NULL`` test would have passed on it and reported 100% resolution.
    """
    return pd.DataFrame([
        {"key": "BIGLAK_PHBL_T1_1|SOZNFRI9", "from_station": "BIGLAKE",
         "to_station": "PHBL_TAP", "from_kv": 69.0, "to_kv": 69.0,
         "mu_mass": 900.0, "bind_hours": 100, "resolved": True, "n_pairs": 1},
        {"key": "HARGRO_TWINBU1_1|DBAKCED5", "from_station": "TWINBU",
         "to_station": "HARGROVE", "from_kv": 138.0, "to_kv": 138.0,
         "mu_mass": 60.0, "bind_hours": 50, "resolved": True, "n_pairs": 1},
        {"key": "E_PASP|BASE CASE", "from_station": None, "to_station": None,
         "from_kv": 0.0, "to_kv": 0.0, "mu_mass": 40.0, "bind_hours": 30,
         "resolved": False, "n_pairs": 1},
        {"key": "THIN|C", "from_station": "SCRCV", "to_station": "KNAPP",
         "from_kv": 138.0, "to_kv": 138.0, "mu_mass": 0.0, "bind_hours": 1,
         "resolved": True, "n_pairs": 1},
    ])


class _FakeConn:
    """Stands in for the settlement-point read in ``name_localization``."""

    def __init__(self, sps: list[str]) -> None:
        self._sps = sps

    def cursor(self):
        conn = self

        class _Cur:
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
            def execute(self_inner, *a, **k): return None
            def fetchall(self_inner): return [(p,) for p in conn._sps]

        return _Cur()


# ------------------------------------------------------------------ leg A

def test_station_resolution_is_mass_weighted_not_key_weighted(keys):
    """3 of 4 keys resolve (0.75) but they carry 0.96 of the mass.

    The two must be reported separately: a covariate reaching most keys but only
    the ones that never bind is worthless, and only the mass number sees that.
    """
    a = station_resolution(keys)
    assert a["n_keys"] == 4
    assert a["n_keys_resolved"] == 3
    assert a["key_share"] == pytest.approx(0.75)
    assert a["station_resolution_mass"] == pytest.approx(960.0 / 1000.0)


def test_stationless_key_does_not_count_as_resolved(keys):
    """The empty-string trap: BASE CASE rows carry '' , not NULL."""
    a = station_resolution(keys)
    assert a["unresolved_mass"] == pytest.approx(40.0)
    assert a["station_resolution_mass"] < 1.0


# ------------------------------------------------------------------ leg B

def test_joinable_mass_is_zero_without_a_named_outage_source(keys):
    """The load-bearing assertion of the whole spike.

    Leg A resolves 96% of mass here. Joinable mass is still **zero**, because a
    join has two sides and ERCOT publishes no transmission-outage feed. If this
    test ever reads 0.96, someone has wired leg A's number into the R4 bar.
    """
    assert joinable_mass(keys, sources=[]) == 0.0


def test_a_new_named_source_forces_a_rescope_rather_than_a_wrong_number(keys):
    """If a named feed is ever ingested, the spike must not quietly guess."""
    with pytest.raises(NotImplementedError, match="re-scope"):
        joinable_mass(keys, sources=["transmission_outages.element"])


# ------------------------------------------------------------------ leg C

def test_name_localization_scores_only_keys_with_both_stations_placed(keys):
    """A key is localizable only if BOTH its stations place — one end is not a
    location. Only BIGLAKE/PHBL_TAP place here, so 900 of 1000 mass localizes."""
    conn = _FakeConn(["BIGLAKE", "PHBL_TAP_UNIT1", "SOMETHING_ELSE"])
    c = name_localization(conn, keys)
    assert c["n_exact"] == 1        # BIGLAKE matches a SP name outright
    assert c["n_prefix"] == 1       # PHBL_TAP -> PHBL_TAP_UNIT1
    assert c["localizable_mass"] == pytest.approx(0.9)


def test_name_localization_ignores_unresolved_keys(keys):
    conn = _FakeConn([])
    c = name_localization(conn, keys)
    assert c["localizable_mass"] == 0.0
    assert c["station_hit_rate"] == 0.0


# ------------------------------------------------------------------ verdict

@pytest.mark.parametrize("mass, tag", [
    (0.976, "BUILD"),                 # what leg A alone would have wrongly bought
    (R4_BUILD_BAR, "BUILD"),
    (R4_BUILD_BAR - 1e-9, "FLAGGED"),
    (R4_FLAGGED_BAR, "FLAGGED"),
    (R4_FLAGGED_BAR - 1e-9, "ZONAL_FALLBACK"),
    (0.0, "ZONAL_FALLBACK"),          # the measured reality
])
def test_verdict_bars(mass, tag):
    assert verdict(mass)[0] == tag
