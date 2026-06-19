WARN[0000] volume "ercotstress_pgdata" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume
[+]  1/1t 1/11
 ✔ Container db Running                                                                                                                                                                                        0.0s
Container db Waiting
Container db Healthy
Container ercotstress-compute-run-f70aedc2aa66 Creating
Container ercotstress-compute-run-f70aedc2aa66 Created
2026-06-19 17:46:32,414 INFO [timing] setup.read_csv.marginal_costs: 1.5 ms
2026-06-19 17:46:32,417 INFO [timing] setup.read_csv.bus_weather_zones: 2.9 ms
2026-06-19 17:46:32,421 INFO [timing] setup.read_csv.gen_enriched: 3.6 ms
2026-06-19 17:46:33,390 INFO [timing] setup.load_network_init: 969.1 ms
2026-06-19 17:46:33,403 INFO [timing] setup.pg_connect: 12.5 ms
2026-06-19 17:46:33,953 INFO [timing] setup.adapter_init: 550.0 ms
2026-06-19 17:46:33,971 INFO [timing] adapter.build._query_load: 18.2 ms
2026-06-19 17:46:33,974 INFO [timing] adapter.build._query_wind: 2.7 ms
2026-06-19 17:46:33,978 INFO [timing] adapter.build._query_solar: 3.0 ms
2026-06-19 17:46:34,039 INFO [timing] adapter.build._query_outages: 61.0 ms
2026-06-19 17:46:34,140 INFO [timing] adapter.build._query_zonal_lmp: 100.8 ms
2026-06-19 17:46:34,209 INFO [timing] adapter.build._build_p_max_pu: 68.6 ms
2026-06-19 17:46:34,263 INFO [timing] adapter.build._derate: 53.8 ms
2026-06-19 17:46:34,263 INFO [timing] adapter.build._scale_loads: 0.3 ms
2026-06-19 17:46:34,264 INFO [timing] run.adapter.build: 310.6 ms
2026-06-19 17:46:34,596 INFO [timing] run.load_network: 332.0 ms
2026-06-19 17:46:34,598 INFO [timing] run.assign_marginal_cost: 1.8 ms
2026-06-19 17:46:34,602 INFO [timing] compute.apply_operating_conditions: 3.7 ms
2026-06-19 17:46:34,624 WARNING The following buses have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009',
       '1010',
       ...
       '13420', '13421', '13422', '13423', '13424', '13425', '13426', '13427',
       '13428', '13429'],
      dtype='str', name='name', length=2751)
2026-06-19 17:46:34,642 WARNING The following generators have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
       ...
       'G1089', 'G1090', 'G1091', 'G1092', 'G1093', 'G1094', 'G1095', 'G1096',
       'G1097', 'G1098'],
      dtype='str', name='name', length=1099)
2026-06-19 17:46:34,686 WARNING The following lines have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
       ...
       'L3983', 'L3984', 'L3985', 'L3986', 'L3987', 'L3988', 'L3989', 'L3990',
       'L3991', 'L3992'],
      dtype='str', name='name', length=3993)
/compute/snapshot.py:58: FutureWarning: The default value of `include_objective_constant` will change from True to False in version 2.0. Set `include_objective_constant` explicitly to suppress this warning. Using False improves LP numerical conditioning by not including the objective constant as a variable.
  net.optimize.create_model()
2026-06-19 17:46:47,075 INFO [timing] optimize.create_model: 12473.1 ms
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
Dependent equations search removed 0 rows and 0 nonzeros in 0.09s (limit = 1000.00s)
2828 rows, 3435 cols, 77723 nonzeros 0s
Presolve reductions: rows 2828(-15403); columns 3435(-3008); nonzeros 77723(-30644)
Solving the presolved LP
Using dual simplex solver
  Iteration        Objective     Infeasibilities num(sum)
          0    -7.0451347585e+00 Pr: 2827(1.74156e+07) 0.4s
       3143     5.6276104577e+05 Pr: 0(0) 2.9s

Performed postsolve
Solving the original LP from the solution after postsolve

Model status        : Optimal
Simplex   iterations: 3143
Objective value     :  5.6276104577e+05
P-D objective error :  5.7818595984e-14
HiGHS run time      :          3.06
2026-06-19 17:46:53,011 INFO [timing] optimize.model_solve: 5936.1 ms
2026-06-19 17:46:53,028 INFO [timing] optimize.assign_solution: 16.3 ms
2026-06-19 17:46:53,033 INFO [timing] optimize.assign_duals: 4.9 ms
2026-06-19 17:47:18,302 INFO [timing] optimize.post_processing: 25268.9 ms
2026-06-19 17:47:18,302 INFO [timing] compute.optimize: 43700.2 ms

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
2026-06-19 17:47:18,319 INFO [timing] compute.print_diag: 16.3 ms
2026-06-19 17:47:24,364 INFO [timing] ptdf.determine_topology: 6018.4 ms
2026-06-19 17:47:27,749 INFO [timing] ptdf.calculate_PTDF: 3385.0 ms
2026-06-19 17:47:32,211 INFO [timing] ptdf.calculate_BODF: 4461.4 ms
2026-06-19 17:47:32,213 INFO [timing] compute.get_ptdf_lodf: 13893.5 ms

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
2026-06-19 17:47:32,805 INFO [timing] compute.fragility: 591.7 ms

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
2026-06-19 17:47:33,358 INFO [timing] compute.contingencies: 552.7 ms
2026-06-19 17:47:33,360 INFO [timing] compute.basis: 1.7 ms
2026-06-19 17:47:33,363 INFO [timing] compute.outputs: 3.5 ms
2026-06-19 17:47:33,363 INFO [timing] run.compute_snapshot: 58765.1 ms
2026-06-19 17:47:33,363 INFO [timing] run_snapshot_for_ts: 59410.2 ms

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
