"""The engine's SP metadata provider must type hubs/LZs by name even when the
geocoded CSV omits them — the whole point of not reusing matrix._sp_metadata."""
from pathlib import Path

import pandas as pd

from compute.analysis.metadata import hub_lz_type, load_sp_metadata


def test_hub_lz_type_is_a_pure_name_rule():
    assert hub_lz_type("HB_WEST") == "hub"
    assert hub_lz_type("HB_HOUSTON") == "hub"
    assert hub_lz_type("LZ_HOUSTON") == "load_zone"
    assert hub_lz_type("HB_BUSAVG") is None   # aggregate, not a location
    assert hub_lz_type("HB_HUBAVG") is None
    assert hub_lz_type("SOMENODE_RN") is None


def test_load_metadata_derives_hubs_without_a_csv():
    # Missing CSV → no error; hubs/LZs still get a derived type, others are None.
    meta = load_sp_metadata(["HB_WEST", "LZ_NORTH", "FOO_RN"], csv_path="/nonexistent.csv")
    assert meta["HB_WEST"]["sp_type"] == "hub"
    assert meta["LZ_NORTH"]["sp_type"] == "load_zone"
    assert meta["FOO_RN"] == {"sp_type": None, "load_zone": None, "lat": None, "lon": None}


def test_csv_supplies_geocode_and_type(tmp_path: Path):
    csv = tmp_path / "geo.csv"
    pd.DataFrame({
        "settlement_point": ["FOO_RN", "HB_WEST"],
        "sp_type": ["RN", None],           # CSV happens to omit the hub's type
        "load_zone": ["LZ_WEST", None],
        "lat": [30.1, None],
        "lon": [-99.2, None],
    }).to_csv(csv, index=False)

    meta = load_sp_metadata(["FOO_RN", "HB_WEST", "MISSING_RN"], csv_path=str(csv))
    # CSV row wins for the resource node.
    assert meta["FOO_RN"] == {"sp_type": "RN", "load_zone": "LZ_WEST",
                              "lat": 30.1, "lon": -99.2}
    # Hub present in the CSV but untyped there still gets the name-derived type.
    assert meta["HB_WEST"]["sp_type"] == "hub"
    # SP absent from the CSV falls back to all-None.
    assert meta["MISSING_RN"]["sp_type"] is None
