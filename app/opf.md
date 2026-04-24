# Debug Session

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
the network object. Needed the `assign_all_duals=Tru`e flag on `n.optimize()`
(Lagrange.)

---

# So Far What's real vs. placeholder

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

# Conceptual PF (v.01) vs Current OPF

* `n.pf()` (AC power flow), not n.`optimize()` (DC-OPF). These are fundamentally
  different computations:

* `n.pf()` (power flow): Takes generator dispatch as given (from the TAMU case
  file's static gen.p_set) and solves for voltages and flows to satisfy
  Kirchhoff's laws. No optimization. Uses whatever dispatch the TAMU case baked
  in.

* `n.optimize()` (DC-OPF): Minimizes total generation cost subject to load
  balance and line limits. Chooses dispatch.

## PF

The TAMU case ships with a pre-computed dispatch that's roughly representative
of summer peak ERCOT — with lots of power flowing long distances from West Texas
wind/panhandle to Houston/Dallas.

No shadow prices anywhere. It's pure topology + loading measure. Every bus gets
a non-zero value because every bus has non-zero PTDFs to every line, and every
line has finite headroom. The log scale made the map look vibrant across the
whole grid.


## OPF

Your validating TAMU fragility against ERCOT basis — the price differential
between zonal and hub LMPs. Basis is purely an economic quantity, driven by
binding transmission constraints and shadow prices.

If your fragility metric is purely structural (v0.1 version: Σ PTDF² /
headroom), it will have weak correlation with basis, because it doesn't know
anything about prices.


The shadow-price-weighted version is the one that's actually apples-to-apples
with basis. That's the whole thesis: can TAMU's synthetic grid predict where
real economic congestion shows up? The fragility metric has to speak the same
language as basis.

## Top Fragility Exploration

Top fragility buses: 5186, 13236, 13368, 5269, 13418, 5092, 5445, 6153, 7293, 13344

       bus0   bus1   s_nom
name
L2692  7016   7365  198.90
L2453  6153  13418  107.37

Buses with highest fragility aren't the direct endpoints of the binding
lines. They're buses that have high PTDFs to those lines without being
directly on them. This can happen in meshed networks

```python
# Which binding line dominates the fragility of bus 5186?
bus_idx = sub_buses.get_loc('5186') if '5186' in sub_buses else list(sub_buses).index('5186')
# Actually sub_buses is an Index; use get_loc or just positional
import pandas as pd

# contributions from each line to bus 5186's fragility
bus_name = '5186'
bus_pos = list(sub_buses).index(bus_name)

# Shadow prices on binding lines
for line_name in ['L2692', 'L2453']:
    line_pos = list(n.lines.index).index(line_name)
    ptdf_val = ptdf[line_pos, bus_pos]
    shadow_val = shadow[line_pos]
    headroom_val = headroom[line_pos]
    contribution = (ptdf_val**2) * shadow_val / headroom_val
    print(f"  Line {line_name}: PTDF={ptdf_val:+.4f}, shadow=${shadow_val:.2f}, "
          f"headroom={headroom_val:.2f}, contribution={contribution:.4f}")
```
for bus 5186, the lines contribute nothing, yet high fragility - exploring why
 Line L2692: PTDF=+0.0015, shadow=$21.27, headroom=1.00, contribution=0.0000
 Line L2453: PTDF=-0.0015, shadow=$12.99, headroom=1.00, contribution=0.0000


```python
# Is bus 5186 a paired node with 13236? (equal fragility suggests a series bus)
# Check their neighbors
for bus in ['5186', '13236', '13368', '5269']:
    # Lines connected to this bus
    connected = n.lines[(n.lines['bus0'] == bus) | (n.lines['bus1'] == bus)]
    print(f"Bus {bus}: {len(connected)} lines connected")
    print(connected[['bus0', 'bus1', 's_nom']].head())
    print()
```

Bus 5186: 6 lines connected
       bus0  bus1   s_nom
name
L1498  5092  5186  225.90
L1732  5177  5186  279.00
L1733  5177  5186  279.00
L1751  5186  5269  165.51
L1752  5186  5355  279.00

Bus 13236: 0 lines connected
Empty DataFrame
Columns: [bus0, bus1, s_nom]
Index: []

Bus 13368: 0 lines connected
Empty DataFrame
Columns: [bus0, bus1, s_nom]
Index: []

Bus 5269: 4 lines connected
       bus0  bus1   s_nom
name
L1751  5186  5269  165.51
L1909  5427  5269  279.00
L1910  5269  5445  279.00
L1911  5445  5269  279.00


Ok, high fragility but no lines on 13236 and 13368?

Buses 13236 and 13368 have no lines connected, but they appear in the top
fragility. That's because they're connected via transformers only — they're
transformer endpoints.

```python
# Check if 5186 and 13236 are connected by a transformer
tx_5186 = n.transformers[(n.transformers['bus0'] == '5186') | (n.transformers['bus1'] == '5186')]
print("Transformers at bus 5186:")
print(tx_5186[['bus0', 'bus1', 's_nom']])
```

Transformers at bus 5186:
       bus0  bus1   s_nom
name
T367  13236  5186  186.01

OK so 5186 and 13236 are the two sides of transformer T367. That's why they have
identical fragility — they're electrically the same node in the DC
approximation.

* The PTDFs are treating transformers as zero-impedance connectors: transformer
  endpoint pair acts as one electrical node.
* Fragility concentrates at binding-line endpoints plus their transformer twins.
  When L1751 binds, both 5186 and 5269 light up — and their transformer twins
  (13236 and 13368) light up too, because they're electrically the same.


```python
# Full breakdown of bus 5186's fragility by line
bus_name = '5186'
bus_pos = list(sub_buses).index(bus_name)

# Per-line contributions to this bus's fragility
ptdf_col = ptdf_lines[:, bus_pos]  # PTDF column for this bus, lines only
contributions = (ptdf_col ** 2) * shadow / headroom

# Top contributors
import pandas as pd
contrib_series = pd.Series(contributions, index=n.lines.index)
print(f"Bus {bus_name} total fragility: {frag[bus_name]:.4f}")
print(f"\nTop 10 lines contributing to bus {bus_name}'s fragility:")
print(contrib_series.sort_values(ascending=False).head(10))

# Also check the underlying values
top_contrib = contrib_series.sort_values(ascending=False).head(10).index
print(f"\nDetails on top contributors:")
for line in top_contrib:
    line_pos = list(n.lines.index).index(line)
    print(f"  {line}: PTDF={ptdf_col[line_pos]:+.4f}, "
          f"shadow=${shadow[line_pos]:.2f}, "
          f"flow={n.lines_t.p0.iloc[0][line]:+.1f} MW, "
          f"s_nom={s_nom[line_pos]:.1f}, "
          f"headroom={headroom[line_pos]:.2f}")
```

Bus 5186 total fragility: 3.0970

Top 10 lines contributing to bus 5186's fragility:
name
L1751    3.096484
L1603    0.000445
L2692    0.000046
L2453    0.000030
L2615    0.000028
L880     0.000009
L3196    0.000006
L2664    0.000000
L2663    0.000000
L2662    0.000000
dtype: float64

Details on top contributors:
  L1751: PTDF=+0.4222, shadow=$17.38, flow=-165.5 MW, s_nom=165.5, headroom=1.00
  L1603: PTDF=+0.0048, shadow=$19.57, flow=-225.9 MW, s_nom=225.9, headroom=1.00
  L2692: PTDF=+0.0015, shadow=$21.27, flow=+198.9 MW, s_nom=198.9, headroom=1.00
  L2453: PTDF=-0.0015, shadow=$12.99, flow=+107.4 MW, s_nom=107.4, headroom=1.00
  L2615: PTDF=+0.0025, shadow=$4.60, flow=-125.2 MW, s_nom=125.2, headroom=1.00
  L880: PTDF=+0.0009, shadow=$9.79, flow=-88.2 MW, s_nom=88.2, headroom=1.00
  L3196: PTDF=+0.0013, shadow=$3.18, flow=-134.1 MW, s_nom=134.1, headroom=1.00
  L2664: PTDF=-0.0000, shadow=$0.00, flow=-52.3 MW, s_nom=198.9, headroom=146.61
  L2663: PTDF=-0.0000, shadow=$0.00, flow=-52.3 MW, s_nom=198.9, headroom=146.61
  L2662: PTDF=+0.0005, shadow=$0.00, flow=+68.9 MW, s_nom=172.6, headroom=103.69


* L1751 is main contributor, and have 7 lines binding with headroom 1.


```python
# Are there non-zero transformer shadow prices?
if 'mu_upper' in n.transformers_t and not n.transformers_t.mu_upper.empty:
    tx_mu_up = n.transformers_t.mu_upper.iloc[0].abs()
    tx_mu_lo = n.transformers_t.mu_lower.iloc[0].abs()
    print(f"Non-zero tx upper: {(tx_mu_up > 0.01).sum()}")
    print(f"Non-zero tx lower: {(tx_mu_lo > 0.01).sum()}")
    print(f"Top 5 tx upper: {tx_mu_up.nlargest(5)}")
    print(f"Top 5 tx lower: {tx_mu_lo.nlargest(5)}")
else:
    print("No tx duals in n.transformers_t")

```

Non-zero tx upper: 0
Non-zero tx lower: 1
Top 5 tx upper: name
T0    0.0
T1    0.0
T2    0.0
T3    0.0
T4    0.0
Name: now, dtype: float64
Top 5 tx lower: name
T662    0.446025
T0      0.000000
T1      0.000000
T2      0.000000
T3      0.000000
