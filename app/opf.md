What we debugged, in order


1. Load was zero

The Texas2k .nc file stores load as static values on each bus (n.loads.p_set
summed to 85,759 MW — correct for summer peak), but the time-series table
n.loads_t.p_set was empty. PyPSA's optimizer reads from the time-series table,
so it thought load was zero. The original n.set_snapshots([0]) call wiped the
snapshot structure without populating the time-series.

Fix: copy static load values into n.loads_t.p_set for the snapshot.


2. Renewables dispatched at 100% capacity

Every generator had p_max_pu = 1.0 (the default), meaning the solver thought
every wind turbine and solar panel could run at full nameplate simultaneously.
Result: wind + solar + battery covered 85% of load, coal and gas barely ran —
physically impossible.

Fix: hand-set capacity factors approximating ERCOT 5 PM August conditions (wind
20%, solar 65%, etc.). Sprint 3 will replace these with real ERCOT telemetry.


3. LMPs were uniform at $28.55 everywhere

After the first two fixes, dispatch looked sane but every bus had the identical
price. Uniform LMPs mean no binding transmission constraints. We verified via
linopy that all line duals were genuinely zero — the TAMU network has enough
line capacity that nothing was constraining the optimum.


Fix (for now): derate line capacities by 5% (×0.95) to force some binding
constraints. This stands in for N-1 reserve margins that real operators
maintain. Sprint 3 replaces this with real outage data from ERCOT.


4. Missing dual assignment

Even after forcing congestion, PyPSA wasn't writing line shadow prices back to
the network object. Needed the assign_all_duals=True flag on n.optimize().

---
So Far What's real vs. placeholder

| Component              | Current                   | To-be Real in Sprint 3+      |
|------------------------|---------------------------|------------------------------|
| Network topology       | Real (TAMU Texas2k)       | Same                         |
| Generator nameplates   | Real (TAMU + EIA-860)     | Same                         |
| Marginal costs         | Fuel-based proxy          | Refined with heat rates      |
| Load                   | Static summer peak        | Live ERCOT zonal demand      |
| Renewable availability | Hand-picked CFs           | ERCOT MIS wind/solar actuals |
| Line derate            | line 10%, transformers 5% | Real outages from NP3-233-CD |

```
Model name          : linopy-problem-smvmmidb
Model status        : Optimal
Simplex   iterations: 3054
Objective value     :  1.4148432913e+06
P-D objective error :  2.1804569857e-14
HiGHS run time      :          2.22
INFO:linopy.constants: Optimization successful:
Status: ok
Termination condition: optimal
Solution: 6443 primals, 18231 duals
Objective: 1.41e+06
Solver model: available
Solver message: Optimal

INFO:pypsa.optimization.optimize:The shadow-prices of the constraints Kirchhoff-Voltage-Law were not assigned to the network.
Status: ok, optimal

Gen: 85759 MW | Load: 85759 MW | Balance: -0.0
LMP: min=21.75, mean=28.85, max=36.21
LMP p5/p50/p95: [28.57 28.84 29.15]

Dispatch by fuel:
carrier
gas        47543.0
solar      21016.0
wind        8365.0
nuclear     4731.0
battery     3567.0
hydro        276.0
coal         262.0
biomass        0.0
other          0.0
oil            0.0
Name: p, dtype: float64

>>> mu = n.lines_t.mu_upper.iloc[0]
... print(f"Non-zero line shadow prices: {(mu.abs() > 0.01).sum()}")
... print(f"Top 10 binding lines (shadow price $/MWh):")
... print(mu.abs().sort_values(ascending=False).head(10))
...
... mu_low = n.lines_t.mu_lower.iloc[0]
... print(f"\nNon-zero lower-bound shadow prices: {(mu_low.abs() > 0.01).sum()}")
...

Non-zero line shadow prices: 2
Top 10 binding lines (shadow price $/MWh):
name
L2692    21.267163
L2453    12.994417
L2653     0.000000
L2654     0.000000
L2655     0.000000
L2656     0.000000
L2657     0.000000
L2658     0.000000
L2659     0.000000
L2660     0.000000
Name: now, dtype: float64


```
