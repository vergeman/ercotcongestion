"""NP1-346-ER unzip + parse + record building. plan/0089 commit 2.

The intermediate code between `ErcotClient.download_archive` (a zip wrapping an xlsx) and
`loaders.load_resource_outages`: unzip → read sheet 2 (`Unplanned Resource Outages`,
header on row 5) → tuples keyed `(posted_date, resource_unit_code, actual_outage_start)`.

Pure: pandas / zipfile only — no psycopg, no network — so `to_records` stays unit-testable
outside the container. Column names are verbatim from the wire (dumped by the probe, not
remembered — 0087's schema was wrong in five fields precisely because it was remembered).
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

SHEET = "Unplanned Resource Outages"
HEADER_ROW = 4          # the data header sits on row 5 of the sheet
ERCOT_TZ = ZoneInfo("America/Chicago")

# Verbatim wire columns. Asserted on parse so a silent schema drift fails loudly rather
# than mapping the wrong field (0087's lesson).
WIRE_COLUMNS = [
    "Resource Name", "Resource Unit Code", "Fuel Type", "Outage Type",
    "Available MW Maximum", "Available MW During Outage",
    "Effective MW Reduction Due to Outage", "Actual Outage Start",
    "Planned End Date", "Actual End Date", "Nature Of Work",
]


def parse_report(content: bytes) -> pd.DataFrame:
    """Zip bytes → the outage table. Keeps only rows with a resource name (drops the
    sheet's trailing "generated at" footer)."""
    z = zipfile.ZipFile(io.BytesIO(content))
    df = pd.read_excel(io.BytesIO(z.read(z.namelist()[0])), SHEET, header=HEADER_ROW)
    missing = [c for c in WIRE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"NP1-346 schema drift — missing wire columns {missing}; "
                         f"got {list(df.columns)}")
    return df[df["Resource Name"].notna()].copy()


# ---------------------------------------------------------------- coercion (pure)

def _ts(value) -> datetime | None:
    """Naive ERCOT Central timestamp → tz-aware UTC. None for empty / NaT.

    Mirrors `loaders._ercot_ts_to_utc`; kept here so this module carries no psycopg
    dependency (which `loaders` imports at module top)."""
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if ts is pd.NaT or pd.isna(ts):
        return None
    dt = ts.to_pydatetime()
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=ERCOT_TZ).astimezone(timezone.utc)


def _f(x) -> float | None:
    """Coerce to float; None for empty/unparseable, and never NaN (Postgres stores NaN
    as a non-null value that `IS NULL` cannot find — see loaders._f)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _txt(x) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s if s and s.lower() != "nan" else None


def to_records(df: pd.DataFrame, posted_date: date) -> list[tuple]:
    """One snapshot + its vintage → insert tuples for `resource_outages`. Pure.

    `posted_date` is the archive document's posting date — the vintage — supplied by the
    caller; it is NOT a row column. Rows with no unit code or no outage start are dropped:
    both are key columns, so an unkeyable row cannot be stored idempotently. Column order
    matches migration 27 / the loader's INSERT."""
    records = []
    for _, r in df.iterrows():
        uc = _txt(r.get("Resource Unit Code"))
        start = _ts(r.get("Actual Outage Start"))
        if not uc or start is None:
            continue
        records.append((
            posted_date, uc, start,
            _txt(r.get("Resource Name")),
            _txt(r.get("Fuel Type")),
            _txt(r.get("Outage Type")),
            _f(r.get("Available MW Maximum")),
            _f(r.get("Available MW During Outage")),
            _f(r.get("Effective MW Reduction Due to Outage")),
            _ts(r.get("Planned End Date")),
            _ts(r.get("Actual End Date")),
            _txt(r.get("Nature Of Work")),
        ))
    return records
