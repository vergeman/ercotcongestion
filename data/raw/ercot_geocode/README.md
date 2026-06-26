# ERCOT Geocode Data

Data sources used to cross reference and geolocate resources behind each LMP print.

## Process

1. NP7-788-CD gets the list of LMP codes
2. Settlement Points gives additional LMP codes, rough regional context and prefix
3. NP3-988-ER - Metadata: links LMP to corporate entity name
4. Stand Alone Generation Resource - Metadata: : A market data press release
   (not ERCOT data source) that maps LMP code to plant name and name plate
   capacity.

The supplemental ones are especially necessary for newer Battery projects.

* `preprocess/geocode_ercot_layer.py`: extraction script
  * several heuristics to enrich LMP with data above, and match with coordinates
    in `/data/processed/master_eia860.csv`.
  * aims on to be more cautious; still a large number of misses
* `/data/raw/review_queue.csv`: some matches, but low confidence flagged for review
* `/data/raw/manual_overrides.csv`: filled with manual searches to best of my
  ability. Used LLMs to ask for locations, if all 3 reported coordinates were
  within 10 km, decided it was fine (defaulted to Claude). However, still a fair
  number of manual lookup needed.

## Data Links

* [NP6-788-CD, LMPs by Resource Nodes, Load Zones and Trading
  Hubs](https://www.ercot.com/mp/data-products/data-product-details?id=NP6-788-CD):
  `cdr.00012300.0000000000000000.20260625.004020.LMPSROSNODENP6788_20260625_004018.csv`
* [NP4-160-SG, Settlement Points List and Electrical Buses
  Mapping](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-160-SG):
  `Settlement_Points_06112026_122819.csv`
* [Stand Alone Generation Resources as of
9.01.25-v2](https://www.ercot.com/files/docs/2025/09/02/Stand-Alone-Generation-Resources-as-of-09.01.25-v2.pdf):
`Stand-Alone-Generation-Resources-as-of-09.01.25-v2.csv` (converted from pdf -> excel -> csv)
* [NP3-988-ER, Resource Decision-Making Entity
  List](https://data.ercot.com/data-product-archive/NP3-988-ER):
  `1242720673.rpt.00010036.0000000000000000.20260625.051259.ResDMEList_25062026.csv`
