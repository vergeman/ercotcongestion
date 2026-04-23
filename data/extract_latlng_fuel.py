"""
extract_latlng_fuel.py:

parse AUX, output bus_coords.csv, gen_fuels.csv, substations.csv

Enriches *.m network which lacks lat/lng, and generator fuel and unit types
"""
import re
import sys
from pathlib import Path
import pandas as pd


def _find_block(text, obj_name, must_contain=None):
    for m in re.finditer(rf'^{obj_name}\s*\(([^)]*)\)', text, re.IGNORECASE | re.MULTILINE):
        field_str = m.group(1)
        content = text[m.end():]
        body = re.search(r'\{(.*?)\}', content, re.DOTALL)
        if body is None:
            continue
        fields = [f.strip().strip('"') for f in field_str.split(',') if f.strip()]
        return fields, body.group(1)
    return None

def _parse_rows(body, fields):
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith('//') or line in ('{', '}'):
            continue
        toks = re.findall(r'"[^"]*"|\S+', line)
        rows.append([t.strip('"') for t in toks[:len(fields)]])
    return pd.DataFrame(rows, columns=fields)


def extract(aux_path):
    aux_path = Path(aux_path)
    out_dir = aux_path.parent
    stem = aux_path.stem # NB: filename sans extension
    text = aux_path.read_text(encoding='utf-8', errors='ignore')


    # SUBSTATIONS (source of lat/lon)
    result = _find_block(text, 'Substation')
    if result is None:
        raise ValueError("No Substation block found")
    fields, body = result

    raw = _parse_rows(body, fields)

    subs = pd.DataFrame({
        'sub': raw['Number'].astype(int),
        'name': raw['Name'],
        'lat': pd.to_numeric(raw['Latitude'], errors='coerce'),
        'lon': pd.to_numeric(raw['Longitude'], errors='coerce'),
    })


    # BUSES (links to substation via SubNumber, then join coords)
    result = _find_block(text, 'Bus')
    if result is None:
        raise ValueError("No Bus block found")
    fields, body = result

    raw = _parse_rows(body, fields)

    buses = pd.DataFrame({
        'bus': raw['Number'].astype(int),
        'sub': pd.to_numeric(raw['SubNumber'], errors='coerce').astype('Int64'),
    })
    buses = buses.merge(subs[['sub', 'lat', 'lon']], on='sub', how='left')



    # GENERATORS (pick Gen block that has FuelTypeCode)
    result = _find_block(text, 'Gen', must_contain='FuelTypeCode')
    if result is None:
        raise ValueError("No Gen block with FuelTypeCode found")
    fields, body = result

    raw = _parse_rows(body, fields)
    gens = pd.DataFrame({
        'bus': raw['BusNum'].astype(int),
        'gen_id': raw['ID'].str.strip(),
        'fuel': raw['FuelTypeCode'],
        'unit_type': raw['UnitTypeCode'],
    })

    # OUT
    buses.to_csv(out_dir / f"{stem}_bus_coords.csv", index=False)
    subs.to_csv(out_dir / f"{stem}_substations.csv", index=False)
    gens.to_csv(out_dir / f"{stem}_gen_fuels.csv", index=False)

    missing = buses[['lat', 'lon']].isna().any(axis=1).sum()
    print(f"bus_coords:  {len(buses)} rows, {missing} missing coords")
    print(f"substations: {len(subs)} rows")
    print(f"gen_fuels:   {len(gens)} rows")
    print(f"fuel counts:\n{gens['fuel'].value_counts()}")


if __name__ == '__main__':
    extract(sys.argv[1])
