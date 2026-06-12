# Notes

* Power System Analysis and Design SI, 7th Edition

## Module 1: Electricity on the Grid [Fundamentals]

* Chapters 2.1 - 2.4


* Gas turbine: burns gas inside the turbine itself
* Steam Turbine: powered by gas, boils water into steam that drives turbine.
* Combined Cycle: uses both, gas turbine first, hot exhaust creates steam to
  spin steam turbine.

* Heat Rate: BTU / kWh - lower is more efficient, less fuel per output.
  * Combined Cycle Gas: 6400 BTU/kWh (53% efficient)
  * Coal: 10,000 BTU/kWh (34% efficient)
  * Theoretical minimum is 3412 BTU/kWh (100% efficient) - because there are
    3412 BTU in 1 kWh.


* Phasor: rotating vector representing sine wave signal
  * V(t) = 120 * cost(377t + 30°)
  * Rewrite as 120 < 30°
  * cost(377t) -> 60Hz AC Waveform.
    * 377: angular frequency, so cost(377t) is one cycle every 1/60 second.
    * 50hz -> cost(314t)

  * V(t) = V_max · cos(ωt + φ)
    * v(t) = instantaneous voltage at time t
    * V_max = peak amplitude
    * ω = angular frequency (377 for 60 Hz)
    * φ = phase angle

* Phase angle: tells where the sine wave starts - where in the wave
  * AC current: voltage continuously oscillates (sine wave) - completes full
    cycle every 1/60 second
    * delivered by wall outlet
  * DC: stays constant at one value - flat line
    * transformer "rectifier" brick - converts AC to DC for electronics



### Complex Power

| Power          | Symbol | Unit | Description                                                                                        |
|----------------|--------|------|----------------------------------------------------------------------------------------------------|
| Real Power     | P      | MW   | Actual work, lights, motors. What gets bought and sold. The "useful" work                          |
| Reactive Power | Q      | MVAr | Energy sloshing back forth, maintains voltage, magnetic field. Necessary but thrown away by DC-OPF |
| Apparent Power | S      | MVA  | \|S\| = sqrt( P^2 + Q^2). Line and transformer ratings in MVA.                                     |

* `j`: bookkeeping sqrt(-1) represents a 90° rotation; shorthand to represent AC phase relationship.

* `S`: Apparent Power has multiple "views":
  * NB: values are all scalars
    * e.g. S = 800 + j 600VA
  * `S = VI`: compute from phasors, which gives complex number: `S = P + jQ`
  * `S = P + jQ`: complex form of above. P is real power, Q is reactive power.
  * `|S|` is magnitude  - apparent power.

* `MW`: megawatt - real power `P`. Actual work.
* "volt amp": literally volts x amp. Measures total power capacity (real +
  reactive) vs MW which is real work.
    * In trivial device, voltage and current are synced, so they do same work.
    * Most complex devices waves current or voltage lag so out of sync - which
      means less work performed.
* `MVAr`: mega volt-amp reactive: Reactive power `Q`. No work, but sloshes back and forth.
* `MVA`: mega volt-amp: apparent power `|S|`. Equipment must be sized for.
* `s_nom` in `MVA`: line ratings limited by current and voltage; not by real work
  at any given time. In PyPSA, `s_nom` is `s` for apparent power, and `nom` for
  nominal limit.


### Network Equations (RLC)

| Circuit Element | Symbol   | Description                                                                                                                |
|-----------------|----------|----------------------------------------------------------------------------------------------------------------------------|
| Impedance       | Z        | AC opposition to current flow (Ohms)                                                                                       |
| Admittance      | Y        | 1 / Z:  inverse of impedance; how easily current flows (Siemens)                                                           |
| Resistance      | R        | AC or DC; causes real power losses - type of wire material, heat in conductor; dissipates energy as heat (Ohms)            |
|                 |          |                                                                                                                            |
| Reactance       | X        | AC only: inductance from magnetic field around the conductor; stores energy - induces back EMF that opposes current (Ohms) |
| Inductance      | L (X\_L) | inductive *reactance*: grows with frequency (Henries)                                                                      |
| Capacitance     | C (X\_C) | capcitive *reactance*: shrinks with frequency                                                                              |
|                 |          |                                                                                                                            |

* Transmission line is two endpoints connected by an impedance `Z`.
  * `Z = R + jX`
    * NB: values are all scalars
      * e.g.: Z = 3 + j4 -> Z = 5 < 53.1° (polar from)
    * `R`: resistance
    * `j`: imaginary unit
    * `X`: reactance
  * `|Z| = sqrt(R^2 + X^2)`: magnitude of impedance

* `X` Reactance components (L and C are physical properties):
  * `L`: Inductance - opposition to electrical flow by inductors - coils.
    * increase opposition w/ AC frequency rise, causes voltage to lead current
  * `C`: Capacitance - opposition to flow by capacitors.
    * decrease opposition w/ AC frequency rises (stored) - causes Voltage to lag current
  * model current and voltage as two separate waves; current as flow, voltage as pressure
  * NB: Reactance isn't directional (more like a coefficient)

* Lines at transmission voltages are dominated by `X` - reactance, not `R`
  resistance (Factor 5 - 10)

* Hierarchy:
  * `Z`: Impedance ->
    * `R`: Resistance
    * `X`: Reactance
      * `L`: Inductive
      * `C`: Capacitive

* "RLC": loads

### Buses

* Bus: node where things connect - generators, loads, lines, transformers.
  * e.g. TAMU ACTIVSg2000: 2000-bus
* PyPSA Bus Types:
  * slack, PV (generation), PQ (load) - necessary for AC power flow, but not for
    DC OPF.

### Bus Admittance Matrix: Y-Bus

* Y-bus: foundational matrix in power system analysis
  * describes how all buses (nodes) in grid are electrically connected
  * in n-bus system, Y-bus is n x n matrix.
  * typically very sparse, normalized to a per-unit (pu) base
* Diagonal (Y_ii): *sum of all* admittances connected to bus `i` (includes
  self-admittance); positive
* Off-diagonal (Y_ij): *negative* admittance of bus i with bus j
* Sparse: in real gird, most buses only have 2-3 connections.

* Example:

```
Y_12 = 2−j6
Y_23 = 1−j3
Y_13 = 1−j2

From above, we construct diagonal as sum (Yii) to generate table below:

Note symmetry in admittance matrix; 1->2, is same as 2->1, NOT negative.

        Bus 1         Bus 2           Bus 3
Bus 1 [ 3−j8         −(2−j6)        −(1−j2) ]
Bus 2 [ −(2−j6)       3−j9          −(1−j3) ]
Bus 3 [ −(1−j2)      −(1−j3)         2−j5   ]
```

* `YV = I`
  * Y: matrix of admittances (line to line)
  * V: 1 x N (col vector) of voltages
  * I: 1 x N (col vector) of current sources


#### Laws and Equivalence Progression

| Law                  | Equation | Use Case                     |
|----------------------|----------|------------------------------|
| DC Ohms Law          | V = IR   | simple resistive circuits    |
| AC Ohms Law          | V = IZ   | Single AC Circuit (w/ phase) |
| Grid                 | I = YV   | Power Network                |
|                      |          |                              |
| Kirchoff Current Law | P = VI   | Power network                |
|                      |          |                              |

* DC: `V = IR`
* AC: `V = IZ`-> `V / Z = I` -> `V * 1/Z = I`  -> `V * Y = I`
  * Where Impedance (`Z`) is ~ "AC Resistance", and inverse (`1/Z`) is Admittance (`Y`)
  * so Y bus-matrix is basically V=IR but for the entire grid

* Kirchoff: sum of currents flowing in equals sum flowing out

### Review Questions

* What is MW/MVAr/MVA?
* Why is `s_nom` in MVA?
* Why is `x` and `r` in separate columns?
* Why DC power ignores `r`

* What's reactance (X) and why code care? It's the imaginary part of line
  impedance (inductive component) - in DC power flow it's the only line
  parameter that matters, since resistance is treated as 0.


## Module 2: Lines and Transformers [Power Transformers]

* Chapters 3.1 - 3.3, 5.1

### Ideal Transformer

* Transformer: transforms voltage up or down
  * Power line 7200V -> Home 240V
  * Power plants have initial high voltage for AC transmission
  * Two Coiled wire (windings) around iron core - ratio between two wires creates a voltage
    step down (100 -> 10) or step up (10 -> 100)

* DC Power flow, transformer is just a branch with reactance connecting two buses - a line.
  * real transformer has a leakage impedance - small reactance.

* Per-Unit System: "normalized" units to simplify circuit calculations
  * typically base values, voltage V and power S, are selected from a circuit,
    applied throughout.
  * Rescales everything to transformer voltage ratios drop out, network analyzed
    as if at single voltage level.

### Transmission Lines

* Transmission line is two endpoints connected by an impedance `Z`.
  * `Z = R + jX`
* Power flows from higher voltage angle to lower angle
* Flow amounts:
  * proportional to angle difference
  * inversely proportional to line reactance

### Review Questions

* What is a line?
* What is a transfomer?
* opf.md: two buses with identical fragility - same node in DC approximation via
  transformer


## Module 3: Power Flow Problem

* Chapter 6.4

### Power Flow

* Three phase circuit: AC power system uses three alternative currents of same
  frequency and voltage, offset each by 120 degrees. Three overlap (sum of 2 'positive'
  cancel out the other 1 'negative' legs) to create flat, constant (flat line) power.
  * Each bus, there is a 'unique' angle offset, with the reference bus (bus 1) having a 0 angle.
  * Power flows are actually decoupled in AC: P-θ(angle) vs Q-V
    * Real Power: P flows from higher angle bus to lower angled one
    * Reactive Power: Q flows from higher magnitude voltage bus to lower buses
    * Neither implies the other
  * DC approximation assumes |V| = 1pu, and ignores Q, relying on angle.

* Power flow determines voltage and angle at each bus in power system
  * (assumes balanced, three-phase steady-state conditions)
  * computes real and reactive power flows
  * power flow problem is formulated as a set of nonlinear algebraic equations
  * But Newton-Raphson commonly used, requires linear algebraic equations in matrix format

* Power Flow Problem: given generation and load at each bus, find the voltage
  magnitudes, angles and resulting line flows that satisfy Kirchhoff's law.

| Variables  | Description       |
|------------|-------------------|
| k          | bus               |
|            |                   |
| Vk         | voltage magnitude |
| θk (sig k) | phase angle       |
| Pk         | real power        |
| Qk         | reactive power    |

* Further break down the "Power types":
  * Pk = Pgk - Plk (real power = real power generator - real power load)
  * Qk = Qgk - Qgk (reactive power = reactive generated - reactive power load)

* Power flow: Two of the variables are inputs, two are unknowns to be computed.
* Bus Types: slack, PV (Gen), PQ (load).
  * bus is generically where all these elements meet (gen, load, lines, transformers)
  * slack (swing or reference) bus: only one (maybe numbered 1.) Voltage
    magnitude 1, angle 0. Computed as P1, Q1.
  * PQ: Load bus; Pk and Qk are input data. Power flow computes Vk, sigk.
    * Most of these buses are load buses.
  * PV: voltage controlled bus; Pk and Vk are input data. Power flow computes Qk and sigK.
    * e.g. generators, capacitors.

* Bus Admittance matrix calculations
  * Admittance is `Y`, which in inverse of Impedance `Z` - lines are described in impedance.
  * Non-diagonals by convention are negative.
    * This is where we get `-1 / Line input` -> `-1 / Z` = `-1 / R - jX`
    * Diagonal is sum of all connected admittances treated as positive
  * to calculate it, need to multiply top and bottom by conjugate of the
    denominator, to turn the divisor from complex into a real number

```
-1 / (.009 + j0.1) -> -0.8928 + j9.91964

-1 / (.009 + j0.1)  * (.009 - j0.1 / .009 - j0.1)  # note the conjugate is subtraction equivalent

-(0.009 - j0.1) / (0.009^2 + 0.1^2)  - the j - sqrt(-1) - becomes squared and becomes 1

-0.009 + j0.1 / (0.010081)   - divide both components of numerator

-0.009 / 0.10081  + j0.1 / 0.010081

-.8928 + j9.9197

```

* now we have Ybus, which we  use in  `I = YV` -> `I = Ybus * V`
  * `I`, unit vector of currents injected into each bus k
  * `V`, the vector of bus voltages.

* DC Power (for comparison)
  * `P` = `V I`
  * Power (watts) = Voltage (volts ) * Current (amps)

* Complex Power Flow (AC) to bus k =
  * `Sk` = `Pk + jQk` = `Vk * Ik`
    * `I = YV` at k.
    * gets us to `Sk = Vk * sumi ( Yki Vi )`*   (plugin I=YV)
  * Expand the terms into polar form, and do bunch of crazy shit, Euler's
    formula, etc.
    * S~k​ = Vk​i ∑ ​Vi​(Gki​−jBki​) [cos(δk​−δi​)+jsin(δk​−δi​)]
    * in a + jb; real is `a`, imaginary is `b` (prefix by `j`)
    * so for real component, just ignore the imaginary (j), and imaginary component
      ignore real
    * Vk​i ∑ ​Vi​(Gki ​−jBki​) [cos(δk​−δi​) + jsin(δk​−δi​)]
    * Vk​i ∑ ​Vi​(Gki * cos(δk​−δi​) + (Gki * jsin(δk​−δi​)) - (jBki * cos(δk​−δi​)) - (jBki * jsin(δk​−δi​))
    * real, ignore terms with `j`, imaginary ignore terms without `j`, remember j*j = 1
      * P = Vk​i ∑ ​Vi​(Gki * cos(δk​−δi​) -  - (jBki * jsin(δk​−δi​))
      * P = Vk​i ∑ ​Vi​(Gki * cos(δk​−δi​) + (Bki * sin(δk​−δi​))

    * imaginary: collect terms with `j`, but ignore the `j` itself
    * Vk​i ∑ ​Vi​ (Gki * cos(δk​−δi​) + (Gki * jsin(δk​−δi​)) - (jBki * cos(δk​−δi​)) - (jBki * jsin(δk​−δi​))
      * Q = Vk​i ∑ ​Vi​( Gki * jsin(δk​−δi​) - jBki * cos(δk​−δi​) )
      * Q = Vk​i ∑ ​Vi​( Gki * sin(δk​−δi​) - Bki * cos(δk​−δi​) )

  * Within `Sk` are "packed" the real component (`Pk`) and imaginary component `Qk`
    * Real(Sk) -> Pk, and Imaginary(Sk) -> Qk
    * G: conductance; real, known. (Siemens) - AC analog of letting energy
      through head (inverse of resistance)
    * B: susceptance; imaginary, known, (Siemens) - AC analog of letting energy
      oscillate (inverse of reactance)
    * `Z = R = jX` impedance
    * `Y = G + jB` admittance - inverse of impedance
      * B is flipped sign for X. (-X)


### Review Questions

* What is a bus?
* Bus-type vocabulary
* What power flow solves


## Module 4: DC Power Flow, PTDF, LODF

* Chapter 6.10: "DC" Power Flow
* PyPSA contingency analysis

### DC Power Flow

* All of this is analogous to `I = Y V` (AC power - Kirchhoff's current law in matrix form)
* "DC": just looks similar to DC Circuit analysis - not actually direct current
  * ERCOT and ISOs use DC for market clearing (AC takes too long)

* Real Power Flow
  * Voltage: how hard you're pushing
  * Angle: when you're pushing - remember power flows because of angle
    differences, out of sync enough to push current through
  * Grid sets up steady-state patterns of angles where angle differences across
    each line cause power to flow and balance every bus
    * power flow solves for these voltages and angles - at each bus.
  * `Pij = (Vi * Vj) / X * sin(θi - θj)`
    * Effectively Vi and Vj are near 1, term treated as 1.0. Voltages don't vary
      much.
  * In DC circuits, magnitude differences drives current.
  * In AC power systems, timing differences (angles) drive real power flow, and
    magnitude differences drive reactive power flow - angles are the important
    variables in the grid.

* Simplify the power flow problem to neglect the Q-V equation with assumptions:
  * voltage magnitudes are constant at 1.0 per unit
  * voltage angle differences are negligible; (sinθ ~= θ).
  * line resistance is negligible: R = 0
  * results in power flow on line from bus j to bus k with reactance (Xjk), or
    the "real power form line i into line j": -> `Pjk = (θj - θk) / Xjk`
  * for bus admittance matrix, Pjk is sum of all admittances


* reduces real power balance equation to `P = -Bθ`
  * `P`: real power, vector of bus injections
  * `-`: negative: depends on our Y-bus convention: if we use negative values for
    non-diagonal lines, we use `-B`. Otherwise we use `B` if we keep a positive
    admittance for lines. Textbook uses `-B`.
  * `B`: imaginary component of Y bus, line reactances (X)
  * `θ`: vector of bus voltage angles


* How do we get from `Pjk = (θj - θk) / Xjk` to `P = -Bθ`?
  * row equation: sum over every line connected to bus j
  * Pij = θj/X - θk/X
  * Pj = θj * sumk (1/Xjk) - sumk (θj / Xjk)
    * first term: θj * sumk (1/Xjk) -> is Bjj - the diagonal
    * second term: sumj (θj * Xij) -> is -Bij, the non-diagonal

| AC                  | DC approximation       |
|---------------------|------------------------|
| I (complex current) | P (real power)         |
| V (complex voltage) | θ (voltage angle)      |
| Y (1/Z: admittance) | B (1/X: "susceptance") |


### PTDFs and LODFs PyPSA: contingency analysis

* [PyPSA Contingency Analysis](https://docs.pypsa.org/latest/user-guide/optimization/contingencies/)

#### SCLOPF

* Security-Constrained Linear Optimal Power Flow (SCLOPF) builds upon LOPF.
* An optimisation with SCLOPF executed `n.optimize.optimize_security_constrained()`
* BODF matrix: Branch Outage Distribution Factor matrix
  * show outage of branch `c` on all branches `b`
  * `pcb = pb + BODFbc * Pc`
  * add constraints to ensure other branches in `b` do not exceed capacity Pb
    after outage of `c`: `|pb,t + BODFbc * pc,t|` <= |Pb|
    * added in `optimize_security_constrained()` method
* common solution: reserve "security margin of branch capacity for
  contingencies", "set `s_max_pu = .7` to prevent line loading above 70% of
  branch capacity


#### BODF Calculation

* Also called LODF (Line Outage Distribution Factor) matrix
  * but PyPSA uses lines and transformers (so becomes branch)

* Incidence Matrix K is branch-bus topology matrix
  * row: branch (line), column bus
  * so arbitrary l1 (Row) goes from bus 1 to bus 2, and  bus 3 is 0 on branch l1
  * and l2 has bus 2 to bus 3 and 0 on bus 1)
  * in BODF K translates between bus and branch

```
lines (branch) from -> to:
  * l1: 1 -> 2
  * l2: 2 -> 3

K =
              bus
            1   2    3
branch
        [
l1         +1   -1   0
l2          0   +1  -1
        ]
```
* Ordering of calculations prior to BODF (topology K -> PTDF -> BODF)
* BODF calculated from PTDF matrix, and incidence matrix K of network

```python
# PyPSA ordering and values: ptdf_lodf.py:get_pdf_lodf(n)

n.determine_network_topology()
sub = n.sub_networks.obj.iloc[0]
sub.calculate_PTDF()
sub.calculate_BODF()

ptdf = np.asarray(sub.PTDF)
bodf = np.asarray(sub.BODF)
n_lines = len(n.lines)
lodf_lines = bodf[:n_lines, :n_lines]
bus_names = list(sub.buses_o)
```

*`BPTDFbc = sumi PTDFbi Kic`
  * `BPTDFbc`: is change in flow on branch `b`, if unit of power is injected at
    `bus0` of branch `c`, and withdrawn from `bus1` of branch `c`
  * if branch `b` is only connection, then `BPTDFbb` = 1, since power can only
    flow between branch itself.


* PTDF: sensitivities of line flows to bus injections
  * What happens when you inject 1 MW at bus b, withdraw 1 MW at a reference bus?
    * What fraction of flow appears on line x? That is the PDTF[x, b]
    * Calculation depends **purely on topology** - on reactances
  * exists because DC power flow is linear, AC has no PTDF analog.
  * `P = B*θ` has solution that distributes flow across all parallel paths,
    inversely proportional to reactance.

* LODF / BODF: describe how line flows redistribute after a single branch trips.
  * if line `c` trips, what fraction of pre-outage flow, ends up redistributed
    onto line x? That is LODF or BODF[x, c] - also **purely from topology**
  * `Pcb = Pb + BODFbc * Pc`: new_flow = flow_base + LODF * flow_base[outage]
  * derived from PTDFs + topology



### Review Questions

* What DC-OPF approximates, what it throws away (voltage magnitudes, reactive power, losses, large angle nonlinerarity)
* Why doesn't power follow shortest path

* Why do PTDFs exist: relationship between bus injections and line flows is a
  fixed matrix determined by topology
* Why code computes PTDF's from topology alone

* Why Sum PTDF^2 * shadow / headroom sums contributions from every line not nearby ones?
* Why fragility can be high at buses electrically connected (through
  transformers) to a binding line, but geographically distant from it?

* Why DC and not AC for market clearing: can't run fast enough, but with DC a
  linear approximation is accurate enough and gives clean LMPs as duals.

* Is transfomer different than line? In DC power flow, both are termed as
  "branches", with reactance between two buses.

* PyPSA SCOPF functions vs N-1 implementation? why don't we use
  `n.optimize.optimize_security_condition`?


## Power Flow Wind and Solar

* Chapter 6.11

### Power Flow Modeling Wind and Solar Generation

* data adapter uses wind/solar at availability level `p_max_pu` from `gen_actual
  / nameplate` - not power flow level

* WTG: "Wind Turbine Generator" - low power ratings: 1-6MW, offshore 10MWs.
* Wind and solar typically aggregated and treated as a single generator, with
  single interconnection

### Review Questions

* How are renewables modeled as PQ vs PV buses
* what happens at bus-type level when wind output varies?
* What does textbook say about renewable variability in steady state studies?
* any context with West Texas wind story and basis?


## Module 6: Power System Economics and Optimization

* Economic Dispatch: generation at lowest minimum total cost.
* Optimal Power Flow: extension of conventional economic dispatch, solving for
  economic dispatch and power flow simultaneously, given transmission line
  constraints.
* Locational Marginal Prices (LMP) - cost variation at different locations.

* Day Ahead Market (DAM)
* Real Time Market (RTM)
* Forward Capacity Market (FCM)
* Financial Transmission Rights (FTR)

* Congestion: phenomenon when low-cost generation can't be delivered to customer
* LMP: location differences in energy production / consumption - means to manage
  congestion in transmission system.
  * producers / consumers each get the LMP at that node, serves to incentivize
    investment
  * LMP = energy + loss + congestion
    * congestion component in the DAM is used to settle FTR.
* Most ISO's use a proxy bus for pricing - arbitrary and doesn't conform to
  power flow.

* DAM: forward financial market, physical or virtual
  * SCUC: Security Constrained Unit Commitment: where market clears / settles
    * depends on physical assets submitting physical operating parameters;
      min,max startup, ramp rate costs, etc.
    * which generators to enable at each hour - yes/no.
    * typically run once for next day (DAM focus), decides schedule
  * allows hedging against RTM
  * DAM closes, solves the SCUC calculation, generated by shadow prices.

* RTM: spot market, physical delivery of electricity
* SCED: security constrained Economic Dispatch
  * given committed units, how to split load right now to minimize cost
  * real time every 5 minutes; balances supply-demand, sets LMPs

* Two settlement system
  * DAM: on DAM LMP's
  * RTM: settles on deltas from cleared DAM position with RTM LMPs.
  * allows hedging; generators / loads to lock in price, arbitrage (virtuals)
    between DAM and RTM.

* Uplift / Make-whole payment: when LMP doesn't cover entire cost of generation,
  used by ISO to incentivize generators to follow ISO dispatch instructions
  * usually to cover start-up costs in starting generation
  * non-convex: e.g. can run 0, or 200-500, so generation curve is non-convex,
    not smooth or continuous.

* FTR: hedge against transmission congestion
  * source and sink
  * collect revenue based on difference of LMP congestion components between
    sink and source locations.
  * ISO sell the FTRs and collect auction revenue, which gets allocated to LSEs,
    transmission owners, etc. Usually settled on DAM.

* FCM: forward capacity market - given energy market price caps, energy market
  revenue alone might not incentivize capital investment.
    * FCM sets generating capacity and provides steady revenue stream in advance

* Interchange Scheduling: ISO to ISO; bid/offer between markets

* Market Management System (MMS)
* Energy Management System (EMS)


### Economic Dispatch

* C(P): function of cost C to generate P power.
  * typically piece-wise, discontinuous
  * cost expressed in BTU/hr, and converted to $ via cost of fuel ($/BTU)
  * heat rate: BTU/kWh = Ci/Pi (ratio of "cost" for that output)
* dC/dP: derivative shows incremental operating cost (remember BTU/hr)
  * when graphed, find the most efficient cost / output.

* For system N generators, total cost Ct is sum of each cost function Ct = C1(P1) + C2(P2)...
* P is total load demand (generated power needed); Pt = P1 + P2...

* All units on economic dispatch should operate at equal incremental operating cost.
* dC1/dP1 = dC2/dP2 = dC3/dP3...
  * Let one unit operate at higher incremental cost than others.
  * if that's the case, we could reduce the cost, by moving generation to lower
    incremental cost units, reducing total operating cost, Ct.
  * we would keep doing this until they equalize - moving 1 MW power from
    expensive to cheaper.
* Eventually the change equalizes and reaches the optimum - that is where the
  slopes (dC/dP) are the same at each output generation's output level. Same
  slope, but might have different costs (heights - on a graph.) because each is
  generating their unique 'P' value.

* This slope is the Lagrange multiplier λ on the power-balance constraint — the
  system marginal cost, $/MWh of meeting one more MW of demand.

* In a perfect system (copper plate), where there is 0 congestion, 0 loss, the
  LMP is the system price, which is the Lagrange multiplier λ we just
  calculated.

* Transmission losses from a unit may be so high, requires replacing the lower
  cost generation, with less-lossy, but more expensive generation.

### SCOPF and OPF Formulations

* Chapter 7.3

* Economic dispatch assumes "perfect copper plates", no limits from elements in
  transmission

* Optimal Power Flow: economic dispatch with power flow analysis (attention to
  transmission limits)
  * "congestion": transformer and line limits due to thermal, voltage, stability
  * DCOPF: used in dispatch because its fast, easy solve
  * AC OPF: includes voltage, angle; real and reactive power injections at each bus
     * use complex, linear programming approach
     * SCOPF with AC model can be too intensive

* "Secure": notion of reliability - if any piece of equipment fails (line trips,
  generator fail, etc) the grid can absorb the change without cascading
  failures, overloads, collapse.
  * N-1 criterion: solve for a stable system with N components and also with one
    of 1 (n-1) removed.
* "Security constraints": find a dispatch such that the current grid operates
  within limits, but every possible single-element outage leaves an operable
  grid within limits.
* For SCOPF, typically first solve base DCOPF (or ACOPF), and then check each
  contingency by adding constraints iteratively

#### DC OPF


* DCOPF: uses linearized dc power flow assumptions
  * no reactive power, shunt/resistive impedance omitted, voltages set to 1
  * solving for real power and bus voltage angles

* `P = -B θ`
  * `B` is the susceptance matrix, `θ` is vector of voltage angles
* `Fjk`: each branch power flow
* `Bjk = 1 / Xjk`, X is reactance
*  `Fjk` =  `Bjk (θj - θk)`

* Goal / Objective: min Ct = sum i to n Ci(Pgi)
  * "min total cost = sum of cost of each generator i, to generate power `Pg`"
    * where `Pgi` is between min of `Pgi`, and max of `Pgi` (min/max capacity of generator)
    * where `Pi` = `Pgi - Pdi`, for all buses i; `Pdi` is load demand at bus i
  * `Fjk` =  `Bjk (θj - θk)` for all branches j to k
    * where power flow `Fjk` between jk is between -F max, F max

* Economic dispatch and Power flow analysis meet in the constraints
  * left side is economic, right side is physics
  * `P = Bθ`
  * `Pgi - Pdi = B θ`
  * `Pgi - Pdi = sum i_to_j (1/Xij * (θi - θj))`


* Solving gives Lagrange multipliers with each of the power balance constraints in `P = -Bθ`
  * multipliers form vector λ = [λ1, λ2,...]
  * marginal cost to serve electricity at each bus int he system
  * in economic dispatch problem, there is no longer one marginal cost λ for
    system; now cost varies by location given transmission constraints require
    more expensive generation
  * this is LMP - locational marginal price.

#### DCOPF Example

| Bus | Min Gen (MW) | Max Gen (MW) | Load (MW) | Cost ($/MWh) |
|-----|--------------|--------------|-----------|--------------|
| 1   | 100          | 400          | 140       | 18           |
| 2   | 150          | 500          | 265       | 22           |
| 3   | 50           | 300          | 415       | 31           |

| Branch from Bus | Branch to Bus | Branch Reactance on 100 MVA base | Branch Flow Limit |
|-----------------|---------------|----------------------------------|-------------------|
| 1               | 2             | .07                              | 180               |
| 1               | 3             | .05                              | 120               |
| 2               | 3             | .18                              | 140               |


Problem: Minimize total generation cost.

1. Formulate the economic dispatch: min Ct(Pt)

* `min Ct(Pt) = 18Pg1 + 22Pg2 + 31Pg3`
* get this directly from the cost of generation

2. Constraints
  * Generation max/min values - economic. Straight from table
    * 100 <= Pg1 <= 400
    * 150 <= Pg2 <= 500
    * 50  <= Pg3 <= 300
  * Branch flow limits - physics
    * `Fjk` =  `Bjk (θj - θk)` where `Bjk` is `1/Xjk`
      * `Xjk` is reactance, which multiply by 100 for 100-MVA base.
      * Branch Flow limit is +/- from table. NB: flow is signed, it has
        direction. But reactance (X) is directionless - just limit.
      * In power flow, Voltages are assumed 1.0, ignored; solving for angles.
    * bus 1 -> 2: -180 <= 100 * 1/.07(θ1 - θ2) <= 180
    * bus 1 -> 3: -120 <= 100 * 1/.05(θ1 - θ3) <= 120
    * bus 2 -> 3: -140 <= 100 * 1/.18(θ2 - θ3) <= 140

3. Setup DC-OCF matrix: `P = -Bθ`

* `B` is like our `I = Y V`, B is our "Y"
* non-diagonals: 1/X
* diagonals: are negative sum of connected buses
```
B=
       1            2       3
  [
1    -(b12+b13)   1/.07   1/.05

2   1/.07    -(b12+b23)   1/.18

3   1/.05        1/.18    -(b13 + b23)

]


B=
     1       2     3

1  -34.28   14.28  20.00

2  14.28    -19.83  5.55

3  20.00    5.55    -25.55
```


```
P = -B θ
P gen - Pload = -B θ  - load taken from table

     P
[           ]                 [    ]
  Pg1 - 140                     θ1
  Pg2 - 265     = -100 *[B] *   θ2
  Pg3 - 415                     θ3
[            ]                [    ]


```

* In a simple example this looks redundant, but for solving larger equations, we
  need to compose Ax=b

* The solver (simplex) solves the "primal solution" to give:
  * the dispatch: `Pg1`, `Pg2`, `Pg3` how much each generator produces.
  * the voltage angle at each bus: `θ1`, `θ2`, `θ3`
    * this isn't really used, but needed to calculate P
* the Lagrange multipliers are additional output from the solver - the duals
  * the duals (λ, μ) are computed simultaneously (not a dependent or sequential
    result from solver)
  * λ is LMP at bus i: marginal cost of one more MW of load
  * μ is shadow price of line; marginal value of one more MW of capacity
    * 0 if within limits; but if binding - then shadow price computed
    * binding: when flow of line *exactly* reaches limit (neither under nor over)
    * shadow price - happens at binding, the variation occurs to express the
      "economic pain" and everything else going on in the system. Not a measure
      of "bindingness" - binding is just a boolean condition.
  * if we decompose LMP, we see it has a system price and PTDF, and μ - but
    defer this discussion for K&S.

### Review Questions

* ERCOT does SCED with N-1 constraints baked directly into objective - no
  overload contingency, baked into dispatch itself.
  * SCED does dispatch solving a larger but relaxed LP; progressively adding
    constraints and re-iterating.
* My code computes contingencies post hoc; run the base case DCOPF, then ask
  what happens to line k - recompute - via LODF
* I check security after dispatch vs SCED guarantees security during dispatch.
* Post-hoc can fail to find a feasible answer at all if base case is insecure;
  SCED finds cheapest secure dispatch.
  * Pricing implication: LMP's include not just base-case congestion, but also
    "contingency congestion" - buses are priced as if certain lines might be overloaded.
  * Since SCED optimizes for security, it "bakes" in that implied price
    component; e.g. the LMP would be lower if security was not a consideration.




---

## PyPSA Walkthrough


### Y-Bus

* TAMU gives `r`, `x` per line
* PyPSA computes `y = 1 / (r + jx)` per branch
* assembled in Y bus admittance matrix
* solves I = YV for grid, (solve voltages and flows)
* remember this is all topology

#### Power Flow

* Given generation and loads,
* Setup P, Q flow equations
* Newton-Raphson iterative solution for voltage magnitude (V) and angle (θ)
* Use V, θ to calculate line flows, generator Q outputs, losses, etc.

Given V, θ, we can calculate everything about grid's operating state.
1. Power flows on every line (MW/MVAR) from bus i to bus j
2. Voltage levels at every load: sagging (brownout ~.92pu) or rising (damage ~1.08pu)
3. Reactive power dispatch: VAR generators must produce vs capability limits
4. System losses: total I^2R across grid
5. Stability margins: how close system to voltage collapse

Use Cases
* Operations: forecast load, generation scheduling, check overloads
* Contingency N-1 Analysis: simulate losing major lines, transformers,
  generators - what holds up.
* Market LMPs: these are derived from power flow solutions; each bus reflects
  congestion and losses - solved from V, θ
* Capacity Planning and Renewable Integration

Reality is power flows according to Kirchhoff's laws and network impedances; its
all voltage and angles - so power flow predicts this routing before something
breaks.

* what is `n.lines.bus0` and `n.lines.bus1`? these are columns populated with
the respective bus ids; e.g. each column is a from bus and to bus; with rest of metrics populated for that pairing

* shunt: `network.shunt_impedances`: "connected to ground" - one bus and ground
  * shunt capcitors, reactors (inductors)
* series: between two buses - lines, transformers - (off-diagonal)
