"""extract_eia860.py

Extract EIA-860 to extract lat/lng of generators

Goal to build a corresponding map between Texas2K dataset labels and ERCOT
Match on lat/long proximity + fuel type + capacity

Merge 2023 and 2024 and filter by unique

2___Plant_Yxxxx.xlsx:
  * Plant Code (Plant ID)
  * lat/lng

3_1_Generator_Yxxxx.xlsx:
  * Plant Code (Plant ID)
  * Generator capacity (Nameplate Capacity MW)


"""
import re
import sys
from pathlib import Path
import pandas as pd


dirs = ["2024", "2023", "2022"]
#dirs = ["2024"]

res = {}
master_df = pd.DataFrame()

for d in dirs:
    data_dir = Path(f"eia860/eia860{d}")
    plant_xlsx = data_dir/f"2___Plant_Y{d}.xlsx"
    gen_xlsx= data_dir/f"3_1_Generator_Y{d}.xlsx"

    print(f"Loading: {data_dir}")

    plant_df = pd.read_excel(plant_xlsx, sheet_name=0, skiprows=1, dtype=str)
    gen_df = pd.read_excel(gen_xlsx, sheet_name=0, skiprows=1, dtype=str)

    plant_df.columns = plant_df.columns.str.strip()

    # Generation Filter TX
    gen_tx = gen_df[gen_df["State"] == "TX"].copy()
    gen_tx = gen_tx[gen_tx["Status"] == "OP"]  # Operating units only hm maybe?

    # Plant Filter TX
    plant_tx = plant_df[plant_df["State"] == "TX"].copy()

    #
    # Make numeric
    #
    # lat/lng in Plant
    for col in ["Latitude", "Longitude"]:
        plant_tx[col] = pd.to_numeric(plant_tx[col], errors="coerce")

    # Nameplate Capacity (MW) in Gen
    for col in ["Nameplate Capacity (MW)"]:
        gen_tx[col] = pd.to_numeric(gen_tx[col], errors="coerce")

    # Inner merge: every operating generator gets its plant info
    gen_tx = gen_tx.drop(columns=['County',  'Utility ID', 'Utility Name', 'Plant Name',
                                  'State', 'Sector', 'Sector Name'], errors='ignore')
    df = gen_tx.merge(plant_tx, on='Plant Code', how='inner')
    df = df.dropna(subset=['Latitude', 'Longitude',
                            'Nameplate Capacity (MW)', 'Energy Source 1'])

    # merge any missing
    master_df = pd.concat([master_df, df])\
                  .drop_duplicates(subset=['Plant Code', 'Generator ID'])\
                  .reset_index(drop=True)


master_df = master_df\
    .dropna(subset=["Latitude", "Longitude", "Nameplate Capacity (MW)", "Energy Source 1"])

master_df.to_csv('processed/master_eia860.csv', index=False)
