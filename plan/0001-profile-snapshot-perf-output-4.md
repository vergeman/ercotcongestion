WARN[0000] volume "ercotstress_pgdata" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume 
[+]  1/1t 1/11
 ✔ Container db Running                                                                                                                                                                                        0.0s
Container db Waiting 
Container db Healthy 
Container ercotstress-compute-run-664367469a78 Creating 
Container ercotstress-compute-run-664367469a78 Created 
2026-06-19 20:37:14,503 INFO [timing] setup.read_csv.marginal_costs: 2.1 ms
2026-06-19 20:37:14,507 INFO [timing] setup.read_csv.bus_weather_zones: 4.0 ms
2026-06-19 20:37:14,513 INFO [timing] setup.read_csv.gen_enriched: 6.0 ms
2026-06-19 20:37:22,280 INFO [timing] setup.load_network_init: 7766.8 ms
2026-06-19 20:37:22,306 INFO [timing] setup.pg_connect: 25.9 ms
2026-06-19 20:37:22,746 INFO [timing] setup.adapter_init: 439.5 ms
2026-06-19 20:37:22,780 INFO [timing] adapter.build._query_load: 34.0 ms
2026-06-19 20:37:22,782 INFO [timing] adapter.build._query_wind: 1.8 ms
2026-06-19 20:37:22,783 INFO [timing] adapter.build._query_solar: 1.6 ms
2026-06-19 20:37:22,832 INFO [timing] adapter.build._query_outages: 48.4 ms
2026-06-19 20:37:22,910 INFO [timing] adapter.build._query_zonal_lmp: 77.7 ms
2026-06-19 20:37:22,965 INFO [timing] adapter.build._build_p_max_pu: 55.2 ms
2026-06-19 20:37:22,996 INFO [timing] adapter.build._derate: 31.2 ms
2026-06-19 20:37:22,996 INFO [timing] adapter.build._scale_loads: 0.1 ms
2026-06-19 20:37:22,997 INFO [timing] run.adapter.build: 250.9 ms
2026-06-19 20:37:23,303 INFO [timing] run.load_network: 306.7 ms
2026-06-19 20:37:23,305 INFO [timing] run.assign_marginal_cost: 1.0 ms
2026-06-19 20:37:23,307 INFO [timing] compute.apply_operating_conditions: 2.6 ms
2026-06-19 20:37:23,323 WARNING The following buses have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009',
       '1010',
       ...
       '13420', '13421', '13422', '13423', '13424', '13425', '13426', '13427',
       '13428', '13429'],
      dtype='str', name='name', length=2751)
2026-06-19 20:37:23,334 WARNING The following generators have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
       ...
       'G1089', 'G1090', 'G1091', 'G1092', 'G1093', 'G1094', 'G1095', 'G1096',
       'G1097', 'G1098'],
      dtype='str', name='name', length=1099)
2026-06-19 20:37:23,359 WARNING The following lines have carriers which are not defined. Run n.sanitize() to add them. Components with undefined carriers:
Index(['L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
       ...
       'L3983', 'L3984', 'L3985', 'L3986', 'L3987', 'L3988', 'L3989', 'L3990',
       'L3991', 'L3992'],
      dtype='str', name='name', length=3993)
/compute/snapshot.py:59: FutureWarning: The default value of `include_objective_constant` will change from True to False in version 2.0. Set `include_objective_constant` explicitly to suppress this warning. Using False improves LP numerical conditioning by not including the objective constant as a variable.
  net.optimize.create_model()
2026-06-19 20:37:33,856 INFO [timing] optimize.create_model: 10548.9 ms
Running HiGHS 1.14.0 (git hash: 7df0786): Copyright (c) 2026 under MIT licence terms
LP has 18231 rows; 6443 cols; 126443 nonzeros
Coefficient ranges:
  Matrix  [6e-02, 5e+02]
  Cost    [2e+00, 2e+02]
  Bound   [0e+00, 0e+00]
  RHS     [6e-02, 4e+03]
Presolving model
3304 rows, 4402 cols, 96721 nonzeros 0s
2834 rows, 3441 cols, 92368 nonzeros 0s
Dependent equations search running on 2834 equations with time limit of 1000.00s
Dependent equations search removed 0 rows and 0 nonzeros in 0.07s (limit = 1000.00s)
2834 rows, 3441 cols, 92368 nonzeros 0s
Presolve reductions: rows 2834(-15397); columns 3441(-3002); nonzeros 92368(-34075) 
Solving the presolved LP
Using dual simplex solver
  Iteration        Objective     Infeasibilities num(sum)
          0    -1.3084968601e+00 Pr: 2833(2.09982e+07) 0.4s
       3054     5.6276104577e+05 Pr: 0(0) 2.1s

Performed postsolve
Solving the original LP from the solution after postsolve

Model status        : Optimal
Simplex   iterations: 3054
Objective value     :  5.6276104577e+05
P-D objective error :  1.6238854328e-14
HiGHS run time      :          2.24
2026-06-19 20:37:38,788 INFO [timing] optimize.model_solve: 4931.1 ms
2026-06-19 20:37:38,796 INFO [timing] optimize.assign_solution: 8.4 ms
2026-06-19 20:37:38,803 INFO [timing] optimize.assign_duals: 7.0 ms
2026-06-19 20:37:38,806 INFO [timing] optimize.post_processing: 2.2 ms
2026-06-19 20:37:38,806 INFO [timing] compute.optimize: 15498.3 ms

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
2026-06-19 20:37:38,815 INFO [timing] compute.print_diag: 8.9 ms
/compute/ptdf_lodf.py:20: FutureWarning: In future versions, adjacency_matrix will return a pandas DataFrame by default. To maintain the current behavior, explicitly set return_dataframe=False. To adopt the new behavior and silence this warning, set return_dataframe=True.
  A = n.adjacency_matrix(branch_components=n.passive_branch_components)
2026-06-19 20:37:39,268 INFO [timing] topology.adjacency: 440.8 ms
2026-06-19 20:37:39,269 INFO [timing] topology.connected_components: 1.0 ms
2026-06-19 20:37:39,285 INFO [timing] topology.subnet_setup: 15.6 ms
2026-06-19 20:37:39,298 INFO [timing] topology.find_bus_controls: 12.5 ms
2026-06-19 20:37:39,298 INFO [timing] ptdf.determine_topology: 470.5 ms
2026-06-19 20:37:41,871 INFO [timing] ptdf.calculate_PTDF: 2573.0 ms
2026-06-19 20:37:45,624 INFO [timing] ptdf.calculate_BODF: 3752.7 ms
2026-06-19 20:37:45,625 INFO [timing] compute.get_ptdf_lodf: 6810.2 ms

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
2026-06-19 20:37:45,990 INFO [timing] compute.fragility: 365.1 ms

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
2026-06-19 20:37:46,342 INFO [timing] compute.contingencies: 351.3 ms
2026-06-19 20:37:46,343 INFO [timing] compute.basis: 1.2 ms
2026-06-19 20:37:46,346 INFO [timing] compute.outputs: 2.7 ms
2026-06-19 20:37:46,346 INFO [timing] run.compute_snapshot: 23041.4 ms
2026-06-19 20:37:46,346 INFO [timing] run_snapshot_for_ts: 23600.5 ms

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
