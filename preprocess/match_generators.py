from matplotlib.pyplot import summer
from scipy.spatial import cKDTree
import numpy as np
import pypsa
import pandas as pd
from pathlib import Path
from constants import CARRIER_TO_EIA
from config import GENERATOR_MATCHES_CSV, MASTER_EIA860_CSV, NETWORK_NC


def match_generators(tamu_df, eia_df, coord_tol_km=10, cap_tol_pct=0.20):
    """Match Logic: for each Texas2K (TAMU) generator, finding closets EIA-860 plant

    We pass each through sequence of filters to see what matches:

    1. Proximity Pass: Convert EIA plant coordinates to radians
       use cKDTree lib (kd tree) to run spatial nearest neighbor query within range.

    2. Fuel Type Pass: Look to fuel type constants to reduce candidates
       If nothing filters matches, then keep the candidate set for next pass

    3. Capacity Pass: Lastly, filter if capacity exceeds 20% diff


    Match quality labels: get a sense how effective all this is
      matched_all      - location + fuel + capacity
      matched_fuel     - location + fuel only (capacity out of range)
      matched_location - location only (fuel type disagreement)
      no_match         - no EIA plant within coord_tol_km

    TOOD: remove County depending on TIGER lookup.

    """
    eia_coords = np.radians(eia_df[["Latitude", "Longitude"]].values)
    tree = cKDTree(eia_coords)
    tol_rad = coord_tol_km / 6371  # search range: 10km / 6371km (earth radius)
                                   # converted to radians
    tamu_coords = np.radians(tamu_df[["lat", "lon"]].values)

    matches = []
    counties = []
    match_quality = []

    for tamu_row, coord in zip(tamu_df.itertuples(), tamu_coords):

        # PROXIMITY PASS
        # given a TAMU coord, return all EIA generators within tol_rad
        idxs = tree.query_ball_point(coord, tol_rad)
        if not idxs:
            matches.append(None)
            match_quality.append('no match')
            counties.append(None)
            continue

        candidates = eia_df.iloc[idxs].copy()

        # FUEL PASS
        # Fuel filter: of candidates to we have fuel matches
        eia_fuels = CARRIER_TO_EIA.get(tamu_row.carrier, [])
        fuel_filtered = (
            candidates[candidates["Energy Source 1"].isin(eia_fuels)]
            if eia_fuels else candidates
        )

        # no match? Keep candidates for subsequent capacity filter
        if fuel_filtered.empty:
            fuel_filtered = candidates  # relax fuel
            quality = 'matched_location'
        else:
            quality = 'matched_all'


        # CAPACITY PASS
        # abs capacity difference in MW: (EIA - TAMU) / TAMU capacity
        # normalized so as to filter at percentage
        cap_diff = (
            (fuel_filtered["Nameplate Capacity (MW)"] - tamu_row.capacity_mw)
            .abs()
            .div(tamu_row.capacity_mw)
        )
        cap_filtered = fuel_filtered[cap_diff <= cap_tol_pct]  # cap_tol_pct e.g. 20% filter

        # if capacity doesn't narrow, but excludes all, then make sure to
        # indicate matched on above fuel filter
        if cap_filtered.empty:
            cap_filtered = fuel_filtered
            if quality == 'matched_all':
                quality = 'matched_fuel'

        # Closest spatially among remaining
        sub_coords = np.radians(cap_filtered[["Latitude", "Longitude"]].values)
        dists = np.linalg.norm(sub_coords - coord, axis=1)

        best = cap_filtered.iloc[np.argmin(dists)]
        matches.append(best["Plant Code"])
        counties.append(best["County"])
        match_quality.append(quality)

    result = tamu_df.copy()
    result["eia_plant_code"] = matches
    result["eia_county"] = counties
    result["match_quality"] = match_quality
    return result


def build_tamu_df(n):
    """
    Extract generator DataFrame from enriched PyPSA network.
    NB: kept x,y prior for quick plotting
    """
    df = n.generators[['bus', 'carrier', 'p_nom']].copy()
    df = df.join(n.buses[['x', 'y', 'sub_id', 'sub_name']], on='bus')
    df = df.rename(columns={'x': 'lon', 'y': 'lat', 'p_nom': 'capacity_mw'})
    return df[['bus', 'lat', 'lon', 'carrier', 'capacity_mw', 'sub_id', 'sub_name']].copy()


def load_eia860(path="master_eia860.csv"):
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()

    # need to make numeric on reload (csv)
    for col in ["Nameplate Capacity (MW)", "Latitude", "Longitude"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna(subset=["Latitude", "Longitude"])


def summarize_matches(result):
    print(f"Total:     {len(result)}")
    print(f"Matched:   {result['eia_plant_code'].notna().sum()}")
    print(f"Unmatched: {result['eia_plant_code'].isna().sum()}")
    print(f"\nMatch quality:\n{result['match_quality'].value_counts()}")
    print(f"\nUnmatched by carrier:\n{result[result['eia_plant_code'].isna()]['carrier'].value_counts()}")
    print(result['eia_county'].notna().sum(), "of", len(result), "have eia county")

    missing = result[result['eia_county'].isna()]
    print(f"Missing county: {len(missing)}")
    print("\nBy match_quality:")
    print(missing['match_quality'].value_counts())
    print("\nBy carrier:")
    print(missing['carrier'].value_counts())

if __name__ == '__main__':

    # Load Network and EIA860 Data
    n = pypsa.Network(NETWORK_NC)
    eia860_df = load_eia860(str(MASTER_EIA860_CSV))

    tamu_df = build_tamu_df(n)
    tamu_df = tamu_df.rename(columns={'p_nom': 'capacity_mw'})

    # MATCH
    result = match_generators(tamu_df, eia860_df)
    summarize_matches(result)

    result.to_csv(GENERATOR_MATCHES_CSV, index=False)
