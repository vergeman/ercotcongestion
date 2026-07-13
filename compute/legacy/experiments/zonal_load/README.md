# Zonal Load Factor Experiments

Current scheme: zonal load + load-shed slack

* Add a high-cost "shed" generator per bus;
* OPF always solves; unserved MW (far_west shortfall) is reported, not hidden.
* No load redistribution so no fake congestion.

* far_west remains under-served, because the synthetic transmission (and
  possibly local generation) is under-built vs real ERCOT.

## Problem

Model mismatch between ERCOT load data and ACTIVSg2000/Texas2k. Far West zone
ACTIVSg2000 model load shaped by *population* (2016 base), while ERCOT load
reflects doubled *industrial* (Permian oil & gas) load.

Synthetic Far West transmission was never grown to match load increase. When
implementing zonal scale factor, every OPF became infeasible under scaled zonal
load (but global factor ok).

Ran a number of experiments to isolate the issue, and tried a handful of
solutions; no scenario choice can really repair a grid that is flawed before the
solve.

End result: use zonal load factors alongside load shed on each bus (mimics local
generation.) Allows feasible OPC, without corrupting other zones. Congestion and
shadow pricing behaves reliably outside of Far West zone, though Far West will
see unrealistic LMP values from flawed modeled congestion.


## Experiments

located in `/compute/experiments/zonal_load`:

| Experiment                           | Sub-directory           |
|--------------------------------------|-------------------------|
| Diagnosis:                           | `feasibility_diagnosis` |
| Cap sweep                            | `cap_sweep`             |
| Line Expansion Candidates            | `line_expansion `       |
| Permian Transmission Line            | `permian_backbone`      |
| Compare LMP load-shed + combinations | `compare_zonal_lmp`     |
| Model Baseline                       | `model_baseline`        |


### Diagnosis

#### Goal

Localize WHY zonal load scaling factor makes the OPF infeasible, but global is ok. It
happens on every reference timestamp. What's going on.

#### Scripts

* `diagnose_zonal_infeasibility.py`

#### Results

* `results.txt`

* far_west sheds 18/20 reference snapshots, and the majority of load.

* Texas2k model far_west ~ 4.7% of load; ERCOT ~ 8–19%.

* If we need to load shed we cannot get power where it's needed - so we have
  transmission bottlenecks. The synthetic far_west transmission undersized for
  real load.

## Load-shed Slack

Load-shed slack: a fake high-cost generator added at every bus. If the grid
can't physically deliver power somewhere, the OPF buys from that fake generator
instead of failing.

* Adds `shed-` to far-west bus.
* Sets Load Shed `SHED_COST` to 5000.
  * Previously set 1e6 was a non-physical placeholder causing 1M LMPs. Set to
    actual $5000 ERCOT offer cap (VOLL).

Probably the most realistic behavior in far west right now (corridor unbuilt,
real load, scarcity priced/curtailed).

Weakness:

* LMP at a shed bus pins to the shed cost, which aren't market prices.
* True infeasibility is now hidden.


### Load Cap Sweep

#### Goal

Can we cap far_west load; instead of scaling, try to keep zonal load shape for
the well-behaved zones, but bound far west and preserve the system.

Recomputes loads at each cap value, capping any ercot zone value and then
redistributing the residual MW to the other zones so the total stays exact.

```
cap_mw = cap * global scale factor * zone
capped = min(ercot_zone, cap_mw)
residual = ercot total - capped total
```

Want highest cap that still shows feasible across all four regimes, to preserve
real load in each case.


#### Scripts

* `cap_sweep.py`
* `caplog.txt`

#### Results

`fw` is far west:

| Cap | Summer Peak      | High Wind West | Mild Shoulder | Winter Peak       |
|-----|------------------|----------------|---------------|-------------------|
| 1.2 | shed 84  (fw 0)  | feasible       | feasible      | feasible          |
| 1.3 | shed 270  (fw 0) | feasible       | feasible      | feasible          |
| 1.5 | shed 228 (fw 3)  | feasible       | feasible      | feasible          |
| 2.0 | shed 259 (fw 86) | feasible       | feasible      | shed 118 (fw 104) |


At cap=1.2 far west shed is 0, but total shed is 84, meaning it moved to other
zones. It does end up meaningfully redistributing, as our code instructs. So Far
west's real peak load can't be served on this topology.

Since goal of this project is to track congestion we need feasible OPF and do
not want to artificially re-distribute load and manufactures congestion.

Motivates zonal factor and load shedding approach.


### Line Expansion Candidates

#### Goal

TAMU Series25 Expansion set has a list of lines in `Candidates.csv` to address
load. It's possible we can try adding top K candidate transmission lines to
reach feasibility with a similar ERCOT load pattern. Real load pattern, and a
more realistic line topology.

#### Scripts

* `far_west_candidates.py`:
  * calcs PTDF for all lines
  * R: filter PTDF for binding lines
  * score topK: mu lines * diff * candidate s1
    * existing lines mu: want candidate lines that link binding lines
    * diff: PTDF (R) - lines that touch candidate line bus; higher diff, the
      candidate moves more flow
    * candidate's s1: high thermal rating can move meaningful flow
  * Greedy top K loop:
    * For each candidate, add to network, OPF calc and check reduced shed (up to
      K OPFs)
    * Found candidate, add permanently to network, then do next round (K-1 OPFS,
      K-2 OPFS)
* `fw_newgen.py`: quick check for the other files GenDispatch*.csv in the
  expansion set to see if it provided news buses, new generation, etc.
* `results.txt`

#### Results

* Line properties: modeled as equivalent low-x AC lines: x_pu/mile ≈ 0.5Ω /
  (765²/100) ≈ 8.5e-5; s_nom ~ 4000 MW.

`RESULT: 3 lines, shed 259->211 MW, cost 47.3`

The candidate lines barely help: Summer peak: baseline shed 259 MW, and after
the 3 best of the top-30 candidates it only drops to 211 MW — an 18% dent.

The real-world answer to handling load is ERCOT's 765 kV Permian backbone that
isn't in this synthetic candidate pool.


### Pilot Permian Backbone

#### Goal

Similar to candidate lines, we have actual planned lines from ERCOT. What
happens if we add those, and leverage ERCOT analysis and decision on a synthetic
grid. What does this do to the synthetic grid load issue?

* To be implemented by ~2030, so not actually seen in the ERCOT data.
* PUCT 2025-04-24: Dinosaur-Long-Drill Hole, Howard–Solstice, Bell-Big Hill–Sand
  Lake).
* Permian Ring: Drill Hole - Sand Lake - Solstice

#### Scripts

* `snap_backbone.py`: lookup nearest bus that match to line expansion path
* `pilot_backbone.py`

```python
SEGMENTS = [
    # bus0, bus1, miles, label, x_mult
    ("5317", "1065", 250.0, "dino_long",       1.0),
    ("1065", "1093",  60.0, "long_drill",      1.0),
    ("5279", "3024", 220.0, "bell_bighill",    1.0),
    ("3024", "13304",177.0, "bighill_sand",    1.0),
    ("4174", "13181",300.0, "howard_sols",     1.0),
    # Permian interior ring
    ("1093", "13304", 45.0, "ring_drill_sand", 1),
    ("13304","13181", 35.0, "ring_sand_sols",  1),
    ("13181","1093",  70.0, "ring_sols_drill", 1),
]
```

* Results:
  * `permian.txt`: permian lines
  * `permian-ring.txt`: permian plus west ring
  * `permian-shed5000.txt`: previous shed cost was set to 1M, now set to 5000.

#### Results

##### Backbone Only

* `_bb`: backbone
* `f_*`: flow between line segment

* Backbone carries real power (up to ~2 GW vs. the dead <300 MW before). But the
  bottleneck moved downstream:

* ~23% relief (1747/7702), 0/20 snapshots fully served
* power reaches the Permian, but can't get from the import buses to every
  shedding bus
* Shed actually rises in a few snapshots: (winter_peak 580 -> 743, mild_shoulder
  399 -> 609)
* summer_peak barely moves (876 -> 804): suggests not transmission-bound,
  backbone can't help.

##### Backbone + Ring

* Ring: (Drill Hole–Sand Lake–Solstice) made it worse looking at the per-segment flows.
* Total relief dropped (1,710 → 1,136 MW)
* 3 segments spiked (mild_shoulder 399 -> 696, winter_peak 580 -> _770, 731 -> 825).

* Ring flows are the culprit:
  * f_ring_drill_sand runs 1,000–3,500 MW
  * f_ring_sand_sols, f_ring_sols_drill carry almost nothing (6–165).

The ring isn't distributing, it's now a low-x shortcut to dump everything onto
the Drill-Sand line, forcing more shed.


## Compare Zonal LMP Schemes

### Two Pass

#### Goal

Given the level of load the grid can actually carry, what are the prices?

* Pass 1: OPF and find the shed; which buses shed and how many MW.
* Pass 2: price the served system. Take the shed MW, subtract them from the load
at those buses. Remove those shed generators entirely, and re-solve a normal
OPF. Now every bus is served by real units, so LMPs and shadow prices are set by
real marginal costs.

* Removing load, not congestion. Important difference.
* Remove unserveable MW, then let the network re-solve freely.
* Every line limit is still enforced, so any congestion that exists at the
  served load level is fully present and priced.

### Zonal LMP Comparison

#### Goal

We have different scenarios, now lets try each scenario or combination, and see
if it follows the behavior of observed ERCOT LMP prices to inform how we handle
load in the model.

When the model sheds, its prices should track ERCOT's scarcity pricing
structurally. Use Spearman Correlation to track movement/structure, but not
levels.

#### Scripts

* `compare_zonal_lmp_optionality.py`: sample set calculate model vs ercot lmp
  across [shed_only, backbone_only, two_pass, backbone + two_pass] load handling
  scenarios.
  * `sample_dates.json`: 150 timestamps for usage as snapshot sample set
* `compare_zonal_lmp.py`: precursor script for above
* `verify_zone_mapping.py`: bus -> weather zone mapping verification
* `west_bootstrap.py`: calculates global spearman rho
  from`compare_zonal_lmp_optionality.py` across scenarios (but not split by
  regions)

#### Results

```
Spearman rho (model vs ERCOT) by scenario x hub:
  scenario           houston     north     south      west
  shed_only            +0.65     +0.41     +0.61     +0.13
  backbone_only        +0.42     +0.44     +0.51     +0.31
  twopass_only         +0.65     +0.43     +0.62     +0.13
  backbone_2pass       +0.43     +0.43     +0.51     +0.21
```

* **Combined Scenarios**: Of primary interest
  * `lmp_compare_scenarios_sample.csv`: sample dates (150) - 4 scenarios lmp model vs ercot
    * `lmp_compare_scenarios_sample_results.txt`: spearman rho calculation by **region**
  * `lmp_compare_scenarios.csv`: reference dates (15) - 4 scenarios lmp model vs ercot

* Price Testing
* `lmp_compare.csv`: reference dates baseline lmp model vs ercot

* Scenario testing
  * `load_shed_only.txt`: load shed on bus, reference dates lmp model v ercot
  * `load_shed_and_periman_backbone.txt`: above + new lines; reference dates lmp
    model v ercot
  * `multipass_lines.txt`: reference dates West hub


### Model Investigation

#### Goals

Get a better idea of where the load exists in the Series25 model.

#### Scripts

* `zone_loading_baseline.py`: load by zone in TAMU model. Make sure we have 2025
  data set.
* `Zone_mapping_audit.py`: far west vs north - is there a region mis-name that's
  separating the load?

#### Results

##### Baseline

```
Model native load by weather zone  (n_loads=1165)
               load_mw  share_pct
zone
north_central  22933.0       26.7
coast          22308.0       26.0
south_central  15944.0       18.6
north           9207.0       10.7
southern        6534.0        7.6
far_west        4053.0        4.7
west            3115.0        3.6
east            1664.0        1.9

TOTAL: 85.8 GW
  ~67 GW  -> 2016 base (original ACTIVSg2000 / Series24 Case 1)
  >80 GW  -> Series25 2025-level

Collapsed to 4 hubs (MW):
hub
houston    23972.0
north      32140.0
south      22478.0
west        7168.0
```

##### Zone Mapping Audit

No smoking gun, not enough to move the needle anywhere.

```
=== per-zone summary ===
               buses  load_buses   load_mw  share_pct
zone
north_central    540         312  22932.62       26.7
coast            562         213  22308.06       26.0
south_central    352         198  15944.50       18.6
north            547         173   9207.46       10.7
southern         299         109   6533.68        7.6
far_west         182          48   4053.36        4.7
west             193          60   3114.77        3.6
east              76          52   1664.44        1.9
TOTAL load 85.8 GW

=== mislabel scan: 50 load buses whose zone != 12-NN neighborhood ===
assigned_zone -> neighborhood_zone  (load that would move if relabeled):
                             buses  load_mw
zone          nbr_zone
north         north_central      4    324.0
              west               4    299.0
north_central north              7    291.0
south_central coast              4    262.0
west          south_central      5    256.0
              far_west           3    219.0
south_central north_central      4    213.0
west          north              3    161.0
east          north_central      4    150.0
west          north_central      2     52.0
coast         south_central      1     47.0
north_central west               1     27.0
south_central southern           3     26.0
north_central south_central      1     25.0
west          southern           2     24.0
east          south_central      1     11.0
              north              1     10.0

Top suspect buses by load:
name          zone      nbr_zone  load_mw       lat         lon
8140 south_central north_central   168.51 30.617778  -96.343333
5116         north north_central   150.06 33.034225  -96.811607
1096          west      far_west   146.12 31.624000 -101.650000
5130         north north_central   141.19 33.021268  -96.741558
1103         north          west   140.63 32.377000 -101.368000
7421 south_central         coast   140.34 30.216858  -95.647214
1104         north          west   125.19 32.377000 -101.368000
3002          west south_central   112.86 30.036701  -99.163039
5431 north_central         north    84.43 32.943901  -96.452875
8072          east north_central    70.08 31.946003  -95.813468
1097          west      far_west    69.42 31.624000 -101.650000
3077          west         north    68.66 32.362783  -99.817314
5043 north_central         north    68.10 32.945503  -96.375325
7202 south_central         coast    65.59 30.099931  -96.065554
3013          west         north    64.56 32.335677  -99.667488
```
