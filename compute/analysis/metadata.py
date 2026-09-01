"""Settlement-point metadata for the brief engine.

This is the engine's *own* metadata provider, deliberately not routed through
``api/matrix.py:_sp_metadata`` (which keys off the geocoded CSV and so silently
drops hubs/LZs that have no geocode). Here the geocoded CSV supplies type and
coordinates for the resource/gen nodes it covers, and hubs/load zones get a
type derived from their name — so ``HB_*`` / ``LZ_*`` never come back untyped
just because they are absent from the geocode file.

The result feeds F2/F4 node dicts (``sp_type``, ``load_zone``, ``lat``,
``lon``); it is best-effort, so a missing CSV yields name-derived hub/LZ types
and ``None`` elsewhere rather than an error.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

# ``*AVG`` hubs are aggregates, not tradable locations.
HUB_AVG_EXCLUDE = frozenset({"HB_BUSAVG", "HB_HUBAVG"})


def hub_lz_type(sp: object) -> str | None:
    """``"hub"`` for ``HB_*`` (bar the ``*AVG`` aggregates), ``"load_zone"`` for
    ``LZ_*``, else ``None`` — a pure name rule, no lookup."""
    s = str(sp)
    if s in HUB_AVG_EXCLUDE:
        return None
    if s.startswith("HB_"):
        return "hub"
    if s.startswith("LZ_"):
        return "load_zone"
    return None


def load_sp_metadata(settlement_points: Iterable[object],
                     csv_path: str | None = None) -> dict[str, dict]:
    """Return ``{sp: {sp_type, load_zone, lat, lon}}`` for every given SP.

    The geocoded CSV (``settings.settlement_points_geocoded_csv`` by default)
    provides the resource-node rows; every SP then gets an entry, and any that is
    still untyped but is a hub/LZ by name receives its derived ``sp_type``. SPs
    absent from the CSV keep ``None`` coordinates.
    """
    sps = [str(sp) for sp in settlement_points]

    from_csv: dict[str, dict] = {}
    if csv_path is None:
        from shared.settings import settings
        csv_path = settings.settlement_points_geocoded_csv
    try:
        df = pd.read_csv(csv_path)
    except (FileNotFoundError, OSError):
        df = None
    if df is not None:
        def _val(row, col):
            v = getattr(row, col, None)
            return None if v is None or pd.isna(v) else v
        for row in df.itertuples(index=False):
            from_csv[str(row.settlement_point)] = {
                "sp_type": _val(row, "sp_type"),
                "load_zone": _val(row, "load_zone"),
                "lat": None if _val(row, "lat") is None else float(row.lat),
                "lon": None if _val(row, "lon") is None else float(row.lon),
            }

    metadata: dict[str, dict] = {}
    for sp in sps:
        entry = dict(from_csv.get(sp, {"sp_type": None, "load_zone": None,
                                       "lat": None, "lon": None}))
        if entry.get("sp_type") is None:
            derived = hub_lz_type(sp)
            if derived is not None:
                entry["sp_type"] = derived
        metadata[sp] = entry
    return metadata
