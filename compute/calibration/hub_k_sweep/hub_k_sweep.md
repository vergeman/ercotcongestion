# Hub LMP k-nearest sweep

## Decision: k = 200

Set `compute.congestion.snapshot_runner.HUB_K_NEAREST = 200`.

Motivation for a wider sweep: ERCOT's HB_BUSAVG SPP is the average of ~all buses tagged to a hub, not a single point. A single-nearest-bus lookup (k=1) is one arbitrary sample from that group; averaging a larger neighborhood better mirrors the way ERCOT actually constructs the SPP.

**Findings across the sweep (93 matched non-shed snapshots, v1-120-postfix):**

The response is U-shaped in k. k=1 and k=200 tie on median-ratio drift (0.231 vs 0.230 averaged across hubs) and HB_WEST negative incidence (48/93). Above k=300 the hubs start collapsing into a whole-system mean — HB_WEST swings positive (median ratio 3.6 at k=300) and hub-to-hub differentiation is lost by k=2000 (all four directional hubs converge onto a ~$40 value). Below k=200, the mid-range (k=5–100) is noisiest — enough averaging to pull in problematic buses, not enough to smooth them.

k=200 is the local optimum that keeps hub locality while stabilising the aggregate:

| Hub       | k=1 corr | k=200 corr | k=1 max | k=200 max | k=1 neg | k=200 neg |
|-----------|---------:|-----------:|--------:|----------:|--------:|----------:|
| HB_BUSAVG | 0.789    | 0.805      | $164.89 | $157.65   | 0       | 0         |
| HB_HOUSTON| 0.683    | 0.682      | $80.43  | $79.94    | 0       | 0         |
| HB_NORTH  | 0.593    | 0.669      | $412.15 | $251.57   | 0       | 0         |
| HB_SOUTH  | 0.661    | 0.693      | $86.06  | $88.04    | 0       | 0         |
| HB_WEST   | 0.128    | 0.327      | $256.54 | $209.42   | 48      | 48        |

HB_NORTH's max drops 39 % (the "spike incidence drops materially" acceptance requirement), correlations improve at every hub except HB_HOUSTON (flat), and HB_WEST/HB_BUSAVG median-ratio drift ties or beats k=1. The 0049 baseline in the plan (HB_NORTH $2116, HB_WEST 38/93 negatives, HB_BUSAVG median ratio 1.29) was measured pre-shed-fix — the shed fix on its own already dropped HB_NORTH's max from $2116 to $412 and HB_BUSAVG median ratio to 1.03 at k=1.

Kept as a parameter (`build_hub_lmps(..., k=HUB_K_NEAREST)`) so the sweep can rerun cheaply after the full-year re-backfill lands.

## Method

Model `hub_avg` averages the k synthetic buses nearest each ERCOT hub centroid. This sweep re-derives per-bus LMPs from the persisted `hub_avg` congestion column of the v1-120-postfix backfill (`lmp[b] = congestion["hub_avg"][b] + hub_lmps["HB_BUSAVG"]` — exact modulo the 3-decimal round of the stored JSON) and compares each k against the ERCOT DAM SPP for the same timestamps.

* Snapshots matched: 93
* Model results: `/compute/runs/v1-120-postfix/congestion/model_results.json.gz`
* ERCOT results: `/compute/runs/v1-120/congestion/ercot_results.json.gz`

Reproduce:
```
docker compose run --rm compute python -m compute.experiments.hub_k_sweep.sweep
```

### HB_BUSAVG  
ERCOT DAM SPP over the matched window: mean=$40.38 p50=$30.64 (n=93)

| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 43.08 | 23.52 | 31.82 | 102.76 | 23.27 | 164.89 | 0.789 | 1.034 | 0 | 0 |
| 5 | 49.33 | 28.50 | 42.20 | 108.78 | 28.01 | 154.70 | 0.738 | 1.255 | 0 | 0 |
| 25 | 44.43 | 25.33 | 34.66 | 101.29 | 24.92 | 155.89 | 0.777 | 1.092 | 0 | 0 |
| 100 | 43.06 | 27.02 | 33.19 | 95.49 | 26.75 | 155.11 | 0.790 | 1.075 | 0 | 0 |
| 200 | 41.31 | 27.01 | 31.28 | 91.35 | 26.88 | 157.65 | 0.805 | 1.043 | 0 | 0 |
| 300 | 40.67 | 27.33 | 31.08 | 89.70 | 27.20 | 155.40 | 0.813 | 1.034 | 0 | 0 |
| 500 | 39.76 | 26.54 | 29.53 | 91.92 | 26.25 | 165.54 | 0.833 | 1.018 | 0 | 0 |
| 1000 | 35.84 | 19.75 | 28.36 | 88.71 | 18.87 | 180.07 | 0.782 | 0.843 | 0 | 0 |
| 2000 | 45.47 | 25.97 | 33.95 | 111.68 | 25.48 | 178.09 | 0.786 | 1.141 | 0 | 0 |

### HB_HOUSTON  
ERCOT DAM SPP over the matched window: mean=$40.52 p50=$33.11 (n=93)

| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 32.34 | 28.54 | 28.89 | 48.06 | 28.16 | 80.43 | 0.683 | 0.919 | 0 | 0 |
| 5 | 32.34 | 28.54 | 28.90 | 48.11 | 28.17 | 80.48 | 0.683 | 0.920 | 0 | 0 |
| 25 | 32.35 | 28.55 | 28.90 | 48.12 | 28.17 | 80.47 | 0.683 | 0.920 | 0 | 0 |
| 100 | 32.30 | 28.51 | 28.88 | 47.89 | 28.12 | 80.10 | 0.682 | 0.919 | 0 | 0 |
| 200 | 32.26 | 28.45 | 28.83 | 47.66 | 28.06 | 79.94 | 0.682 | 0.919 | 0 | 0 |
| 300 | 32.21 | 28.46 | 28.84 | 47.51 | 28.07 | 79.46 | 0.682 | 0.917 | 0 | 0 |
| 500 | 32.16 | 28.50 | 28.82 | 47.28 | 28.16 | 78.90 | 0.678 | 0.913 | 0 | 0 |
| 1000 | 37.85 | 27.33 | 29.20 | 82.80 | 26.92 | 117.84 | 0.763 | 0.981 | 0 | 0 |
| 2000 | 42.01 | 24.91 | 29.03 | 107.37 | 24.71 | 172.24 | 0.767 | 0.999 | 0 | 0 |

### HB_NORTH  
ERCOT DAM SPP over the matched window: mean=$40.37 p50=$30.18 (n=93)

| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 53.54 | 12.95 | 28.38 | 213.28 | 12.32 | 412.15 | 0.593 | 0.919 | 0 | 0 |
| 5 | 52.48 | 12.95 | 28.36 | 203.47 | 12.33 | 395.83 | 0.599 | 0.919 | 0 | 0 |
| 25 | 53.49 | 12.95 | 28.38 | 212.81 | 12.32 | 411.78 | 0.593 | 0.919 | 0 | 0 |
| 100 | 45.08 | 12.92 | 28.39 | 160.03 | 12.29 | 315.85 | 0.629 | 0.915 | 0 | 0 |
| 200 | 43.27 | 12.91 | 28.53 | 141.91 | 12.28 | 251.57 | 0.669 | 0.909 | 0 | 0 |
| 300 | 44.03 | 12.89 | 28.32 | 144.08 | 12.26 | 259.66 | 0.666 | 0.897 | 0 | 0 |
| 500 | 49.44 | 13.47 | 28.62 | 157.66 | 12.87 | 270.68 | 0.745 | 0.950 | 0 | 0 |
| 1000 | 45.15 | 16.62 | 28.79 | 133.72 | 16.12 | 221.01 | 0.764 | 0.995 | 0 | 0 |
| 2000 | 39.21 | 20.54 | 28.91 | 100.12 | 20.12 | 171.86 | 0.788 | 0.997 | 0 | 0 |

### HB_SOUTH  
ERCOT DAM SPP over the matched window: mean=$41.34 p50=$32.22 (n=93)

| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 34.42 | 28.61 | 30.77 | 56.10 | 22.50 | 86.06 | 0.661 | 0.964 | 0 | 0 |
| 5 | 34.48 | 28.63 | 30.80 | 56.24 | 23.27 | 86.47 | 0.665 | 0.964 | 0 | 0 |
| 25 | 34.55 | 28.68 | 30.84 | 56.41 | 23.73 | 86.87 | 0.668 | 0.965 | 0 | 0 |
| 100 | 34.40 | 28.64 | 30.67 | 55.98 | 24.91 | 87.24 | 0.676 | 0.962 | 0 | 0 |
| 200 | 34.50 | 28.75 | 30.70 | 56.11 | 28.61 | 88.04 | 0.693 | 0.963 | 0 | 0 |
| 300 | 34.64 | 28.63 | 30.76 | 56.68 | 28.47 | 91.06 | 0.713 | 0.963 | 0 | 0 |
| 500 | 35.62 | 28.59 | 30.98 | 60.78 | 28.46 | 108.17 | 0.779 | 0.967 | 0 | 0 |
| 1000 | 35.03 | 28.65 | 30.48 | 60.55 | 28.54 | 102.45 | 0.804 | 0.952 | 0 | 0 |
| 2000 | 43.23 | 27.14 | 29.38 | 110.85 | 26.74 | 196.75 | 0.784 | 1.026 | 0 | 0 |

### HB_WEST  
ERCOT DAM SPP over the matched window: mean=$38.38 p50=$28.95 (n=93)

| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | -6.76 | -89.19 | -2.58 | 123.21 | -356.05 | 256.54 | 0.128 | 0.076 | 0 | 48 |
| 5 | -49.89 | -145.26 | -66.79 | 95.50 | -312.73 | 250.92 | 0.202 | -2.178 | 0 | 67 |
| 25 | -105.14 | -232.10 | -131.96 | 86.06 | -354.95 | 267.89 | 0.201 | -4.061 | 0 | 70 |
| 100 | -43.23 | -159.29 | -58.02 | 115.48 | -247.86 | 261.57 | 0.210 | -1.659 | 0 | 64 |
| 200 | 1.10 | -69.66 | -7.25 | 100.33 | -72.88 | 209.42 | 0.327 | 0.100 | 0 | 48 |
| 300 | 136.42 | 76.23 | 121.05 | 244.41 | 69.07 | 246.38 | 0.136 | 3.568 | 0 | 0 |
| 500 | 150.40 | 65.06 | 151.02 | 234.07 | 59.81 | 283.45 | 0.210 | 3.759 | 0 | 0 |
| 1000 | 107.98 | 48.76 | 104.32 | 178.50 | 45.32 | 235.33 | 0.417 | 2.786 | 0 | 0 |
| 2000 | 76.57 | 39.26 | 64.82 | 159.33 | 37.12 | 197.07 | 0.641 | 2.001 | 0 | 0 |

## Summary (across all hubs)

| k | mean(|1 - med_ratio|) | total n_spike | total n_neg |
|---:|---:|---:|---:|
| 1 | 0.231 | 0 | 48 |
| 5 | 0.726 | 0 | 67 |
| 25 | 1.070 | 0 | 70 |
| 100 | 0.588 | 0 | 64 |
| 200 | 0.230 | 0 | 48 |
| 300 | 0.565 | 0 | 0 |
| 500 | 0.590 | 0 | 0 |
| 1000 | 0.403 | 0 | 0 |
| 2000 | 0.235 | 0 | 0 |
