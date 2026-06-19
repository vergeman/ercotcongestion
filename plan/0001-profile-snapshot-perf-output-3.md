WARN[0000] volume "ercotstress_pgdata" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume
[+]  1/1t 1/11
 ✔ Container db Running                                                                                                                                                                                        0.0s
Container db Waiting
Container db Healthy
Container ercotstress-compute-run-12ccfcd2f182 Creating
Container ercotstress-compute-run-12ccfcd2f182 Created
2026-06-19 18:28:39,644 INFO [timing] setup.read_csv.marginal_costs: 3.7 ms
2026-06-19 18:28:39,650 INFO [timing] setup.read_csv.bus_weather_zones: 6.0 ms
2026-06-19 18:28:39,656 INFO [timing] setup.read_csv.gen_enriched: 5.2 ms
2026-06-19 18:28:40,655 INFO [timing] setup.load_network_init: 999.2 ms
2026-06-19 18:28:40,680 INFO [timing] setup.pg_connect: 24.0 ms
2026-06-19 18:28:41,341 INFO [timing] setup.adapter_init: 660.4 ms
2026-06-19 18:28:41,356 INFO [timing] adapter.build._query_load: 14.5 ms
2026-06-19 18:28:41,358 INFO [timing] adapter.build._query_wind: 2.5 ms
2026-06-19 18:28:41,361 INFO [timing] adapter.build._query_solar: 2.5 ms
2026-06-19 18:28:41,407 INFO [timing] adapter.build._query_outages: 45.7 ms
2026-06-19 18:28:41,481 INFO [timing] adapter.build._query_zonal_lmp: 73.3 ms
2026-06-19 18:28:41,539 INFO [timing] adapter.build._build_p_max_pu: 58.1 ms
2026-06-19 18:28:41,596 INFO [timing] adapter.build._derate: 57.1 ms
2026-06-19 18:28:41,596 INFO [timing] adapter.build._scale_loads: 0.1 ms
2026-06-19 18:28:41,597 INFO [timing] run.adapter.build: 255.6 ms
2026-06-19 18:28:42,135 INFO [timing] run.load_network: 537.8 ms
2026-06-19 18:28:42,138 INFO [timing] run.assign_marginal_cost: 2.9 ms
2026-06-19 18:28:42,141 INFO [timing] compute.apply_operating_conditions: 2.5 ms
2026-06-19 18:28:42,163 WARNING The following buses have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009',
       '1010',
       ...
       '13420', '13421', '13422', '13423', '13424', '13425', '13426', '13427',
       '13428', '13429'],
      dtype='str', name='name', length=2751)
2026-06-19 18:28:42,183 WARNING The following generators have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
       ...
       'G1089', 'G1090', 'G1091', 'G1092', 'G1093', 'G1094', 'G1095', 'G1096',
       'G1097', 'G1098'],
      dtype='str', name='name', length=1099)
2026-06-19 18:28:42,226 WARNING The following lines have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
       ...
       'L3983', 'L3984', 'L3985', 'L3986', 'L3987', 'L3988', 'L3989', 'L3990',
       'L3991', 'L3992'],
      dtype='str', name='name', length=3993)
/compute/snapshot.py:59: FutureWarning: The default value of `include_objective_constant` will change from True to False in version 2.0. Set `include_objective_constant` explicitly to suppress this warning. Using False improves LP numerical conditioning by not including the objective constant as a variable.
  net.optimize.create_model()
2026-06-19 18:28:57,163 INFO [timing] optimize.create_model: 15021.6 ms
Running HiGHS 1.14.0 (git hash: 7df0786): Copyright (c) 2026 under MIT licence terms
LP has 18231 rows; 6443 cols; 108367 nonzeros
Coefficient ranges:
  Matrix  [6e-02, 5e+02]
  Cost    [2e+00, 2e+02]
  Bound   [0e+00, 0e+00]
  RHS     [6e-02, 4e+03]
Presolving model
3304 rows, 4402 cols, 81720 nonzeros 0s
2829 rows, 3436 cols, 77725 nonzeros 0s
Dependent equations search running on 2828 equations with time limit of 1000.00s
Dependent equations search removed 0 rows and 0 nonzeros in 0.12s (limit = 1000.00s)
2828 rows, 3435 cols, 77723 nonzeros 0s
Presolve reductions: rows 2828(-15403); columns 3435(-3008); nonzeros 77723(-30644)
Solving the presolved LP
Using dual simplex solver
  Iteration        Objective     Infeasibilities num(sum)
          0    -7.0451347585e+00 Pr: 2827(1.74156e+07) 0.6s
       3143     5.6276104577e+05 Pr: 0(0) 3.4s

Performed postsolve
Solving the original LP from the solution after postsolve

Model status        : Optimal
Simplex   iterations: 3143
Objective value     :  5.6276104577e+05
P-D objective error :  5.7818595984e-14
HiGHS run time      :          3.54
2026-06-19 18:29:04,531 INFO [timing] optimize.model_solve: 7367.7 ms
2026-06-19 18:29:04,544 INFO [timing] optimize.assign_solution: 13.4 ms
2026-06-19 18:29:04,550 INFO [timing] optimize.assign_duals: 6.0 ms
2026-06-19 18:29:04,556 INFO [timing] optimize.post_processing: 5.3 ms
2026-06-19 18:29:04,556 INFO [timing] compute.optimize: 22415.1 ms

Gen: 66473 MW | Load: 66473 MW | Balance: +0.0
LMP: min=-0.00, mean=28.52, max=37.75
LMP p5/p50/p95: [28.26 28.56 28.8 ]

Dispatch by fuel:
carrier
solar      23103.0
gas        18641.0
wind       18283.0
battery     3379.0
nuclear     2897.0
hydro        171.0
biomass        0.0
coal           0.0
other          0.0
oil            0.0
Name: p, dtype: float64
2026-06-19 18:29:04,565 INFO [timing] compute.print_diag: 8.9 ms
2026-06-19 18:29:11,450 INFO [timing] ptdf.determine_topology: 6861.3 ms
2026-06-19 18:29:16,086 INFO [timing] ptdf.calculate_PTDF: 4632.4 ms
2026-06-19 18:29:21,625 INFO [timing] ptdf.calculate_BODF: 5535.2 ms
2026-06-19 18:29:21,627 INFO [timing] compute.get_ptdf_lodf: 17061.9 ms

Fragility stats:
count    2751.000000
mean        0.036377
std         0.548136
min         0.000000
25%         0.000304
50%         0.000655
75%         0.001314
max        17.070720
Name: fragility, dtype: float64

Top 10 most fragile buses:
13333    17.070720
13334    17.070720
13099     9.028369
13100     9.028369
6134      6.683740
6140      2.107824
12690     1.791043
13097     1.676871
13098     1.676871
13107     1.545909
Name: fragility, dtype: float64
Fragility: total=100.07, mean=0.0364, p95=0.0100, p99=0.6614
Buses above p95 (0.010): 138
Buses above p99 (0.661): 28
Buses with fragility > 0.1: 60
Buses with fragility > 0.01: 138
Top 10 buses hold 67.6% of total fragility
2026-06-19 18:29:23,365 INFO [timing] compute.fragility: 1737.6 ms

Top 10 most dangerous N-1 contingencies:
         stress
line
L3704  1.991228
L2837  1.445522
L2020  0.865366
L3905  0.845488
L2036  0.762525
L3688  0.662138
L1926  0.625281
L2769  0.532111
L3852  0.453457
L3026  0.420266

If L3704 trips (base flow: 759 MW, s_nom: 1830 MW):
  5 lines become overloaded
  Top 5 newly-overloaded lines:
name
L1925    1.257198
L1926    0.383477
L1927    0.190849
L1892    0.158870
L3755    0.000835
dtype: float64
2026-06-19 18:29:24,331 INFO [timing] compute.contingencies: 965.7 ms
2026-06-19 18:29:24,332 INFO [timing] compute.basis: 1.0 ms
2026-06-19 18:29:24,336 INFO [timing] compute.outputs: 3.2 ms
2026-06-19 18:29:24,336 INFO [timing] run.compute_snapshot: 42197.4 ms
2026-06-19 18:29:24,336 INFO [timing] run_snapshot_for_ts: 42994.7 ms

============================================================
Snapshot for 2026-03-25T22:00:00+00:00
============================================================
Status: ok
Load:      66,473 MW
Gen:       66,473 MW
Cost:  $   562,761
LMPs:  $-0.00 – $37.75  (mean $28.52)
Binding lines: 3
Fragility total: 100.07
Top 10 share:    67.6%

Top 10 fragile buses:
13334    17.071
13333    17.071
13100     9.028
13099     9.028
6134      6.684
6140      2.108
12690     1.791
13098     1.677
13097     1.677
13107     1.546

Top 5 binding lines:
name
L3755    47.64
L2416    24.59
L1892     2.32
