# Shed adapter fix — full v1-120 canary vs baseline

Baseline: `/compute/runs/v1-120/congestion/model_results.json.gz`  
Candidate: `/compute/runs/v1-120-postfix/congestion/model_results.json.gz`

Records: baseline=120, candidate=120, matched=120, only-baseline=0, only-candidate=0


## Regime rollup — Δ = candidate − baseline

### load_shed_mw

| regime | stats |
|---|---|
| high_wind_west | n=30 | mean=-235.95 | median=-241.75 | min=-359.48 | max=-71.42 |
| mild_shoulder | n=30 | mean=-203.20 | median=-196.25 | min=-311.92 | max=-101.41 |
| summer_peak | n=30 | mean=-163.67 | median=-147.45 | min=-582.63 | max=-59.89 |
| winter_peak | n=30 | mean=-258.04 | median=-238.64 | min=-591.85 | max=-81.32 |

### lmp_mean

| regime | stats |
|---|---|
| high_wind_west | n=30 | mean=-14.62 | median=-16.74 | min=-73.08 | max=-0.21 |
| mild_shoulder | n=30 | mean=-22.54 | median=-19.35 | min=-118.56 | max=+3.00 |
| summer_peak | n=30 | mean=-59.45 | median=-50.69 | min=-161.73 | max=+0.17 |
| winter_peak | n=30 | mean=-88.07 | median=-51.51 | min=-412.38 | max=-5.59 |

### lmp_max

| regime | stats |
|---|---|
| high_wind_west | n=30 | mean=-153.70 | median=-175.97 | min=-434.58 | max=-19.25 |
| mild_shoulder | n=30 | mean=-188.85 | median=-152.16 | min=-1071.79 | max=+317.76 |
| summer_peak | n=30 | mean=-1188.69 | median=-1205.86 | min=-2527.44 | max=+540.92 |
| winter_peak | n=30 | mean=-248.67 | median=-117.18 | min=-2417.08 | max=+305.31 |

### lmp_min

| regime | stats |
|---|---|
| high_wind_west | n=30 | mean=-294.65 | median=-457.48 | min=-660.35 | max=+82.55 |
| mild_shoulder | n=30 | mean=-368.92 | median=-660.80 | min=-1267.98 | max=+1168.05 |
| summer_peak | n=30 | mean=+1259.85 | median=+833.66 | min=-763.05 | max=+4138.49 |
| winter_peak | n=30 | mean=+182.23 | median=-146.97 | min=-851.52 | max=+3153.58 |

### shed-active count (load_shed_mw > 0)

| regime | baseline | candidate |
|---|---|---|
| high_wind_west | 30 | 30 |
| mild_shoulder | 30 | 30 |
| summer_peak | 30 | 30 |
| winter_peak | 30 | 29 |

## Top 20 timestamps by baseline shed

| regime | ts | baseline shed | candidate shed | Δshed | baseline lmp_mean | candidate lmp_mean | baseline lmp_max | candidate lmp_max |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| winter_peak | 2025-01-22T13:00:00+00:00 | 1035.9 | 582.3 | -453.6 | 298.02 | 194.92 | 5000.00 | 4485.31 |
| summer_peak | 2025-08-19T19:00:00+00:00 | 886.1 | 303.5 | -582.6 | 321.11 | 159.39 | 5000.00 | 4531.18 |
| winter_peak | 2025-02-19T17:00:00+00:00 | 824.3 | 297.0 | -527.3 | 258.22 | 142.86 | 4571.52 | 4876.83 |
| winter_peak | 2025-02-20T14:00:00+00:00 | 809.9 | 218.0 | -591.9 | 511.26 | 168.25 | 5000.00 | 4514.62 |
| winter_peak | 2026-01-18T13:00:00+00:00 | 804.5 | 525.6 | -279.0 | 98.05 | 85.30 | 4525.18 | 4484.62 |
| winter_peak | 2025-01-07T13:00:00+00:00 | 738.6 | 414.8 | -323.8 | 207.28 | 111.54 | 4540.88 | 4431.09 |
| winter_peak | 2025-01-23T13:00:00+00:00 | 711.6 | 387.0 | -324.6 | 134.81 | 93.41 | 4556.95 | 4428.72 |
| winter_peak | 2025-01-08T13:00:00+00:00 | 706.1 | 400.8 | -305.2 | 125.28 | 96.53 | 4574.20 | 4406.51 |
| high_wind_west | 2025-11-30T03:00:00+00:00 | 678.0 | 429.8 | -248.2 | 77.93 | 71.92 | 4503.01 | 4471.24 |
| high_wind_west | 2025-01-22T09:00:00+00:00 | 660.1 | 300.6 | -359.5 | 203.23 | 130.15 | 4747.37 | 4312.79 |
| high_wind_west | 2025-12-20T02:00:00+00:00 | 653.6 | 397.0 | -256.6 | 79.43 | 71.93 | 4501.52 | 4470.51 |
| high_wind_west | 2026-05-19T03:00:00+00:00 | 621.9 | 363.9 | -258.0 | 91.70 | 84.75 | 4560.34 | 4481.42 |
| high_wind_west | 2025-11-12T03:00:00+00:00 | 621.8 | 371.1 | -250.7 | 78.74 | 71.93 | 4500.42 | 4470.41 |
| mild_shoulder | 2025-03-24T08:00:00+00:00 | 614.9 | 316.6 | -298.3 | 171.51 | 55.07 | 5000.00 | 4400.24 |
| high_wind_west | 2025-12-12T02:00:00+00:00 | 607.7 | 356.8 | -250.9 | 77.34 | 73.75 | 4497.27 | 4470.95 |
| mild_shoulder | 2025-03-28T09:00:00+00:00 | 607.5 | 295.6 | -311.9 | 170.28 | 51.72 | 5000.00 | 4399.91 |
| high_wind_west | 2025-12-10T02:00:00+00:00 | 600.7 | 348.5 | -252.2 | 77.39 | 72.58 | 4497.74 | 4470.67 |
| high_wind_west | 2026-05-18T03:00:00+00:00 | 599.1 | 340.5 | -258.6 | 85.26 | 77.41 | 4502.37 | 4475.92 |
| mild_shoulder | 2025-04-12T09:00:00+00:00 | 596.8 | 353.3 | -243.5 | 77.20 | 71.75 | 4504.34 | 4473.51 |
| mild_shoulder | 2025-11-01T09:00:00+00:00 | 593.0 | 345.3 | -247.7 | 71.01 | 53.59 | 4500.35 | 4403.98 |
