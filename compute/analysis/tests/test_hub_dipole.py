"""Golden test for F5a — the hub/LZ dipole at 2026-06-30 HE17.

The fixture (``fixtures/june30_he17_hubs.npz``) carries the full forecast-μ̂
vector plus the *full* SF columns of the 13 canonical hubs/LZs (all 1057
constraints), so ``cong`` over the hubs and the driver waterfall are both exact.
Hubs live in the artifact by name, so F5a needs no geocoded metadata.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/analysis/tests/test_hub_dipole.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.analysis.brief import nodal_congestion, pair_contributions
from compute.analysis.families import canonical_hubs, hub_dipole

FIXTURE = Path(__file__).parent / "fixtures" / "june30_he17_hubs.npz"


@pytest.fixture
def hub_day():
    """(hub_SF, mu, hubs) for 2026-06-30 HE17; hub_SF spans all constraints."""
    z = np.load(FIXTURE, allow_pickle=True)
    constraints = [str(c) for c in z["constraints"]]
    hubs = [str(h) for h in z["hub_names"]]
    mu = pd.Series(z["mu"], index=constraints)
    SF = pd.DataFrame(z["hub_sf"], index=constraints, columns=hubs)
    return SF, mu, hubs


def test_canonical_hubs_excludes_averages(hub_day):
    _, _, hubs = hub_day
    assert len(hubs) == 13
    assert "HB_BUSAVG" not in hubs and "HB_HUBAVG" not in hubs
    assert {"HB_PAN", "HB_WEST", "HB_HOUSTON", "LZ_HOUSTON", "LZ_WEST"} <= set(hubs)
    # Derived purely from names, no metadata needed.
    assert canonical_hubs(hubs + ["HB_BUSAVG", "SOMENODE_RN"]) == sorted(hubs)


def test_hub_dipole_spread_and_drivers(hub_day):
    SF, mu, hubs = hub_day
    cong = nodal_congestion(SF, mu)
    res = hub_dipole(cong, SF, mu, hubs)

    # West/Panhandle import vs Houston export — the one-sentence market read.
    assert res["min"]["settlement_point"] == "HB_PAN"
    assert res["min"]["cong"] == pytest.approx(-18.09, abs=0.02)
    assert res["max"]["settlement_point"] == "LZ_HOUSTON"
    assert res["max"]["cong"] == pytest.approx(15.81, abs=0.02)
    assert res["spread"] == pytest.approx(33.90, abs=0.02)

    top = res["drivers"][0]
    assert top["constraint_key"] == "WESTEX|BASE CASE"
    assert top["contribution"] == pytest.approx(7.88, abs=0.02)
    assert top["share"] == pytest.approx(0.232, abs=0.005)
    assert res["drivers"][1]["constraint_key"] == "107__B|SHC2EXC5"

    # The full pair waterfall reconciles exactly to the spread (the top-N list
    # is only its head).
    full = pair_contributions(SF, mu, sink="LZ_HOUSTON", source="HB_PAN")
    assert full.sum() == pytest.approx(res["spread"], abs=0.02)

    # Per-hub vector is complete and sorted ascending by congestion.
    congs = [h["cong"] for h in res["hubs"]]
    assert len(res["hubs"]) == 13
    assert congs == sorted(congs)
