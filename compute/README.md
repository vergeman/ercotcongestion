# Compute

* `config.py`: config object that pulls from `/shared/settings.py`; kept to
  reduce changes during development.

* `constants.py`: carrers, regions, and `DEFAULT_P_MAX_PU` availability ceilings.

* `backfill_basis.py`: catch up script to populate `basis` value in
  `bus_snapshots` table.


## Overview

| Quantity                    | Source                                | Measures                                             |
|:----------------------------|:--------------------------------------|:-----------------------------------------------------|
| **LMP**                     | OPF duals (per-bus power balance)     | Current clearing price                               |
| **Shadow Price** $\mu_\ell$ | OPF duals (per-line thermal limit)    | Severity of current congestion on line $\ell$        |
| **PTDF**                    | Topology                              | Sensitivity of line flows to bus injections (static) |
| **LODF**                    | Topology                              | Redistribution of flow when a line trips (static)    |
| **Fragility**               | PTDF + LODF + flows + contingency set | LMP dispersion caused by N-1                         |
| **Basis**                   | Stored LMP − ERCOT zonal LMP          | Model error vs. reality                              |



### LMP from OPF

* LMP as dual variable (Lagrane Multiplier) of nodal power balance constraint at
  each bus's
  * if added 1 MW of demand at this bus, how much would total system cost go up?
  * `LMP b​ = ∂(total cost) / ∂(load at bus b) `

* PyPSA's DC-OPF
  * primal variables: generator dispatch, line flows
  * dual variables (one per constraint) - "duals" - per-bus power balance
    equations are the LMPs: `n.buses_t.marginal_price`
  * textbook definition: LMP = energy + congestion + losses - uses PTDF as
    "interpretation"
    * Energy: system price
    * Congestion: sum of line l across buses: PTDF l,b * μℓ (shadow price on line l)
    * Losses: 0 in DC-OPF
  * Attribute LMP to PTDF, but they come from LP (linear program - the
    optimization problem solved by OPF) duals.

* Fragility PTDF + LODF + N-1:
  * PTDF: Power Transfer Distribution Factor: L X B (line by bus) matrix
    * inject 1 mW at bus b, what fraction flows through line l
    * pure topology; computed once per network
  * LODF: Line Outage Distribution Factor: L x L matrix
    * LODF l,k: if line k trips,what fraction of k's flow ends up on line l
    * derived from PTDF + topology
    * also pure topology/structure
  * Contingency Loop: For each line outage k, in top-K (fragility) use LODF and
    compute new flows on every other line.
    * avoid re-solving the OPF.
  * Map to buses: If contingency k shows fragility; map back to buses by
    aggregating all top K lines to bus to get single fragility number.

* Model LMP vs Fragility
  * both outputs of OPF, share root cause, transmission congestion
  * LMP:
    * in uncongested network, system cost goes up by marginal generator cost
      (default max)
    * on transmission bind, buses now served by more expensive local
      generation - LMP rises
    * importing side buses have surplus cheap generation; LMP falls zero even
      negative.
  * Fragility: how much do LMP's disperse if a line tripped
    * ask OPF to solve each N-1, and see price variation at bus - fragile if bus
      has substantial price variation.
      * Fragility can be non-zero when LMPs are flat - network that is
        precarious, close to congestion. Ideal scenario to monitor, as prices
        could rise substantially and fan out.

* To Basis:
  * measures how "wrong" the model is
  * fragility: bus is structurally exposed to congestion-drive price variance
  * basis: real-world price diverged from the zonal benchmark
  * correlations - does fragility predict basis?
    * do fragile buses also price differently (basis) from zonal hub?
  * so now does basis capture spatial difference? A calibration or level error?
    etc.

* From OPF:
  * LMP: what are prices today
  * Fragility: how do prices respond to stress
  * Basis: how right/wrong is answer

* Shadow Prices: Lines
