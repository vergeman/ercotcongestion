ergeman@vergeman-zeus:~/dev/ercotstress/docs$ docker compose run --rm compute python /compute/test_snapshot.py
WARN[0000] volume "ercotstress_pgdata" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume
[+]  1/1t 1/11
 ✔ Container db Running                                                                                                                                                                                        0.0s
Container db Waiting
Container db Healthy
Container ercotstress-compute-run-07a94cf644a9 Creating
Container ercotstress-compute-run-07a94cf644a9 Created
2026-06-19 17:20:33,016 INFO [timing] setup.read_csv.marginal_costs: 1.6 ms
2026-06-19 17:20:33,019 INFO [timing] setup.read_csv.bus_weather_zones: 3.0 ms
2026-06-19 17:20:33,022 INFO [timing] setup.read_csv.gen_enriched: 3.4 ms
2026-06-19 17:20:35,816 INFO [timing] setup.load_network_init: 2793.7 ms
2026-06-19 17:20:35,836 INFO [timing] setup.pg_connect: 19.3 ms
2026-06-19 17:20:36,311 INFO [timing] setup.adapter_init: 475.4 ms
2026-06-19 17:20:36,329 INFO [timing] adapter.build._query_load: 17.3 ms
2026-06-19 17:20:36,330 INFO [timing] adapter.build._query_wind: 1.7 ms
2026-06-19 17:20:36,332 INFO [timing] adapter.build._query_solar: 1.9 ms
2026-06-19 17:20:36,387 INFO [timing] adapter.build._query_outages: 54.6 ms
2026-06-19 17:20:36,464 INFO [timing] adapter.build._query_zonal_lmp: 76.8 ms
2026-06-19 17:20:36,523 INFO [timing] adapter.build._build_p_max_pu: 59.3 ms
2026-06-19 17:20:36,558 INFO [timing] adapter.build._derate: 34.2 ms
2026-06-19 17:20:36,558 INFO [timing] adapter.build._scale_loads: 0.2 ms
2026-06-19 17:20:36,558 INFO [timing] run.adapter.build: 247.2 ms
2026-06-19 17:20:36,918 INFO [timing] run.load_network: 359.4 ms
2026-06-19 17:20:36,919 INFO [timing] run.assign_marginal_cost: 1.2 ms
2026-06-19 17:20:36,922 INFO [timing] compute.apply_operating_conditions: 2.8 ms
2026-06-19 17:20:36,935 WARNING The following buses have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009',
       '1010',
       ...
       '13420', '13421', '13422', '13423', '13424', '13425', '13426', '13427',
       '13428', '13429'],
      dtype='str', name='name', length=2751)
2026-06-19 17:20:36,949 WARNING The following generators have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
       ...
       'G1089', 'G1090', 'G1091', 'G1092', 'G1093', 'G1094', 'G1095', 'G1096',
       'G1097', 'G1098'],
      dtype='str', name='name', length=1099)
2026-06-19 17:20:36,976 WARNING The following lines have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
       ...
       'L3983', 'L3984', 'L3985', 'L3986', 'L3987', 'L3988', 'L3989', 'L3990',
       'L3991', 'L3992'],
      dtype='str', name='name', length=3993)
/compute/snapshot.py:53: FutureWarning: The default value of `include_objective_constant` will change from True to False in version 2.0. Set `include_objective_constant` explicitly to suppress this warning. Using False improves LP numerical conditioning by not including the objective constant as a variable.
  net.optimize.create_model()
2026-06-19 17:20:48,658 INFO [timing] optimize.create_model: 11735.7 ms
Running HiGHS 1.14.0 (git hash: 7df0786): Copyright (c) 2026 under MIT licence terms
LP linopy-problem-kaq3f6uz has 18231 rows; 6443 cols; 108367 nonzeros
Coefficient ranges:
  Matrix  [6e-02, 5e+02]
  Cost    [2e+00, 2e+02]
  Bound   [0e+00, 0e+00]
  RHS     [6e-02, 4e+03]
Presolving model
3304 rows, 4402 cols, 81720 nonzeros 0s
2829 rows, 3436 cols, 77725 nonzeros 0s
Dependent equations search running on 2828 equations with time limit of 1000.00s
Dependent equations search removed 0 rows and 0 nonzeros in 0.07s (limit = 1000.00s)
2828 rows, 3435 cols, 77723 nonzeros 0s
Presolve reductions: rows 2828(-15403); columns 3435(-3008); nonzeros 77723(-30644)
Solving the presolved LP
Using dual simplex solver
  Iteration        Objective     Infeasibilities num(sum)
          0    -7.0451347585e+00 Pr: 2827(1.74156e+07) 0.3s
       3185     5.6276104578e+05 Pr: 0(0) 2.2s

Performed postsolve
Solving the original LP from the solution after postsolve

Model name          : linopy-problem-kaq3f6uz
Model status        : Optimal
Simplex   iterations: 3185
Objective value     :  5.6276104577e+05
P-D objective error :  5.7818595984e-14
HiGHS run time      :          2.31
2026-06-19 17:21:07,492 INFO [timing] optimize.solve_model: 18834.2 ms
2026-06-19 17:21:19,312 INFO [timing] optimize.assign_solution: 11818.9 ms
2026-06-19 17:21:21,996 INFO [timing] optimize.assign_duals: 2684.5 ms
2026-06-19 17:21:21,996 INFO [timing] compute.optimize: 45074.0 ms

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
2026-06-19 17:21:22,003 INFO [timing] compute.print_diag: 6.8 ms
2026-06-19 17:21:27,756 INFO [timing] ptdf.determine_topology: 5740.0 ms
2026-06-19 17:21:30,872 INFO [timing] ptdf.calculate_PTDF: 3115.2 ms
2026-06-19 17:21:34,788 INFO [timing] ptdf.calculate_BODF: 3916.0 ms
2026-06-19 17:21:34,789 INFO [timing] compute.get_ptdf_lodf: 12785.9 ms

Fragility stats:
count    2751.0
mean        0.0
std         0.0
min         0.0
25%         0.0
50%         0.0
75%         0.0
max         0.0
Name: fragility, dtype: float64

Top 10 most fragile buses:
7098    0.0
1006    0.0
1008    0.0
1009    0.0
1011    0.0
1021    0.0
1023    0.0
1024    0.0
1026    0.0
1033    0.0
Name: fragility, dtype: float64
Fragility: total=0.00, mean=0.0000, p95=0.0000, p99=0.0000
Buses above p95 (0.000): 0
Buses above p99 (0.000): 0
Buses with fragility > 0.1: 0
Buses with fragility > 0.01: 0
2026-06-19 17:21:35,507 INFO [timing] compute.fragility: 717.1 ms

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
2026-06-19 17:21:36,129 INFO [timing] compute.contingencies: 622.5 ms
2026-06-19 17:21:36,132 INFO [timing] compute.basis: 1.8 ms
2026-06-19 17:21:36,134 INFO [timing] compute.outputs: 2.6 ms
2026-06-19 17:21:36,134 INFO [timing] run.compute_snapshot: 59214.8 ms
2026-06-19 17:21:36,135 INFO [timing] run_snapshot_for_ts: 59823.3 ms

============================================================
Snapshot for 2026-03-25T22:00:00+00:00
============================================================
Status: ok
Load:      66,473 MW
Gen:       66,473 MW
Cost:  $   562,761
LMPs:  $-0.00 – $37.75  (mean $28.52)
Binding lines: 0
Fragility total: 0.00
Top 10 share:    0.0%

Top 10 fragile buses:
7098    0.0
1006    0.0
1008    0.0
1009    0.0
1011    0.0
1021    0.0
1023    0.0
1024    0.0
1026    0.0
1033    0.0
