from scipy.spatial import cKDTree
import numpy as np
import pypsa
import pandas as pd
from pathlib import Path
from constants import CARRIER_TO_EIA

# Load pre-built enriched network — no need to re-import/re-enrich
case_stem = "Texas2k_series25_case1_summerpeak"
d = Path("/data/processed")
n = pypsa.Network(d/f"{case_stem}.nc")



def match_generators(tamu_df, eia_df, coord_tol_km=10, cap_tol_pct=0.20):
    eia_coords = np.radians(eia_df[["Latitude", "Longitude"]].values)
    tree = cKDTree(eia_coords)
    tol_rad = coord_tol_km / 6371
    tamu_coords = np.radians(tamu_df[["lat", "lon"]].values)

    matches = []
    match_quality = []

    for tamu_row, coord in zip(tamu_df.itertuples(), tamu_coords):
        idxs = tree.query_ball_point(coord, tol_rad)
        if not idxs:
            matches.append(None)
            match_quality.append('none')
            continue

        candidates = eia_df.iloc[idxs].copy()

        # Fuel filter
        eia_fuels = CARRIER_TO_EIA.get(tamu_row.carrier, [])
        fuel_filtered = (
            candidates[candidates["Energy Source 1"].isin(eia_fuels)]
            if eia_fuels else candidates
        )

        if fuel_filtered.empty:
            fuel_filtered = candidates  # relax fuel
            quality = 'relaxed_fuel'
        else:
            quality = 'exact'

        # Capacity filter
        cap_diff = (
            (fuel_filtered["Nameplate Capacity (MW)"] - tamu_row.capacity_mw)
            .abs()
            .div(tamu_row.capacity_mw)
        )
        cap_filtered = fuel_filtered[cap_diff <= cap_tol_pct]

        if cap_filtered.empty:
            cap_filtered = fuel_filtered  # relax capacity
            if quality == 'exact':
                quality = 'relaxed_cap'

        # Closest spatially among remaining
        sub_coords = np.radians(cap_filtered[["Latitude", "Longitude"]].values)
        dists = np.linalg.norm(sub_coords - coord, axis=1)
        matches.append(cap_filtered.iloc[np.argmin(dists)]["Plant Code"])
        match_quality.append(quality)

    result = tamu_df.copy()
    result["eia_plant_code"] = matches
    result["match_quality"] = match_quality
    return result


def build_tamu_df(n):
    """Extract generator DataFrame from enriched PyPSA network."""
    df = n.generators[['bus', 'carrier', 'p_nom']].copy()
    df = df.join(n.buses[['x', 'y', 'sub_id', 'sub_name']], on='bus')
    df = df.rename(columns={'x': 'lon', 'y': 'lat', 'p_nom': 'capacity_mw'})
    return df[['bus', 'lat', 'lon', 'carrier', 'capacity_mw', 'sub_id', 'sub_name']].copy()


def load_eia860(path="master_eia860.csv"):
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()

    for col in ["Nameplate Capacity (MW)", "Latitude", "Longitude"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna(subset=["Latitude", "Longitude"])


def summarize_matches(result):
    print(f"Total:     {len(result)}")
    print(f"Matched:   {result['eia_plant_code'].notna().sum()}")
    print(f"Unmatched: {result['eia_plant_code'].isna().sum()}")
    print(f"\nMatch quality:\n{result['match_quality'].value_counts()}")
    print(f"\nUnmatched by carrier:\n{result[result['eia_plant_code'].isna()]['carrier'].value_counts()}")

tamu_df = build_tamu_df(n)
tamu_df = tamu_df.rename(columns={'p_nom': 'capacity_mw'})

eia860_df = load_eia860("processed/master_eia860.csv")
result = match_generators(tamu_df, eia860_df)
