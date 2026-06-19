# Fundamentals of Power System Economics - Kirschen & Strbac Notes

## Markets (Chp 2,3,4)

* SMP: System Marginal Price
  * price of one additional MWh of energy; where demand and generator offers
    clear
  * cheaper offers are filled at market price (higher)
  * pay where market clears, not what each generator offers to encourage
    submitted offers reflect cost of production
    * otherwise generators would submit where they think market would clear to
      max revenue - which would be higher; a suboptimal market

* Bid Offer stack: Price(Y) vs Qty(X) MWh
  * Generators offer cost of generation, and slopes up (at discrete points) as qty increases
  * Bids are high then slope down (discretely)
  * intersection is SMP: where sellers sell (higher) and buyers buy (lower)
  * Realistically consumer demand is inelastic, so bids are just a vertical line at qty.

* Starting generation can take several hours -> Day Ahead Market

* Complex bid to day-ahead: startup cost, incremental cost curve, constraints
  * combined with load forecast to determine generation schedule (on/off) and
    how much to produce -> unit commitment

* Objective: min total cost of operating system next-day

* Uplift payments: external to market payment to recover startup costs

* Spot Market - "last resort" / Real time.
  * more of a managed spot market, needs to be overseen by system operator
  * handles imbalances between participant committed and what it actually did
    * e.g. generator sold 100MW, but only produced 97MW - difference managed by
    system operator at spot

* Gate Closure: forward markets must close at some point before real time to
give the system operator control over what happens in the system

* Spot prices: function more driven by liquidity; flexible generation tends to
  be fewer and more expensive.
  * Generators and consumers report net energy positions
  * contracted to sell vs actual (excess or negative)
  * imbalances are charged at spot, handled by system operator
  * Two-settlement: DA vs RT

* Example: Borduira Power
  * Operator has 40MWh generation deficit, asks Borduria spot generation offer
    (or "bid" in example parlance, SMB-1)
  * Borduira Unit B can only produce 10 of the 80MWH scheduled to produce. Borduria is -70MW.
  * Spot price is $18.25. (OK, so how is spot price actually set here, prior to assigning generation?)

* Storage:
  * Flatten load profile, keep Nukes constantly running via pumped Hydro, allows
    cycling consumption/production.
  * Temporal arbitrage w/ batteries

* Consumption:
  * Flexible demand, similar to storage in the form of heat, manufacturing
    process, etc.*
  * Price vs incentive based load reduction

* Market Power
  * Offer curve for generation; negative at small amounts, then relatively
    flat, until extreme spike
    * Negative prices at small amounts of generation; plants don't want to shut
      off / restart
    * relatively flat incremental pricing for bullk
  * Demand curve: not completely vertical; bulk of demand is inelastic submitted
    without price, but there are some bids submitted with pricing to "bend"
      vertical curve.

## Physics Layer: Network and DC Power Flow

* 5.3.1, 5.3.4

###  Physical Transmission Rights

* Physical Transmission Right: load paying for right for purchases of power

* KCL: Kirchhoff's Current Law: sum of currents entering node equal to sum of
  currents exiting.
  * implies active and reactive power are both in balance at each node

* KVL: Kirchhoff's Voltage Law: sum of voltage drops are zero or equal; since
  proportional to current flowing through branch, KVL determines distribution of
  power within network.

* PTDF: Power Transfer Distribution Factors: factors relating active power
  injections and branch flows

* Equations
  * `Z = R + jX ~= jX`  (resistance is ignored)
  * Flow is reactance / total reactance * power
  * `Fa = Xb / (Xa + Xb) * P`
  * `Fb = Xa / (Xa + Xb) * P`

* Example 3-bus
  * Bus 1: Ga, Gb, load Z
  * Bus 2: Gc, load X
  * Bus 3: Gd, load Y

```
Ga ---> |
        |-------------|
Gb ---> |             |---Gc
        |             |
 Z <--- | 1         2 | --- X
        |             |
        |      3      |
        | ------------|
            |    |
            |    |
            Y    Gd
```

| Branch | Reactance | Capacity (MW) |
|--------|-----------|---------------|
| 1-2    | 0.2       | 126           |
| 1-3    | 0.2       | 250           |
| 2-3    | 0.1       | 130           |


* Gb offers power to load Y: 400MW (bus 1 -> bus 3)
  * power flows  F1: 1 -> 2 -> 3, and F2: 1 -> 3
  * KEY: power splits inversely proportional to reactance
    * in this specific 3 bus example, it's the other path's reactance over total
    * for larger systems, it would be the B matrix (P=Bθ)
  * FI: (1->2->3) = .2       / (.2 + .1 + .2) * P = .2 / .5 * P = 2/5 * 400 = 160
  * FII: (1->3)    = .2 + .1  / (.2 + .1 + .2) * P = .3 / .5 * P = 3/5 * 400 = 240

* 1->2->3 is limited by 1->2, which has 126 capacity, which our 160 exceeds - infeasible.
* Our max power flow on 1->2->3 is limited by line 1-2. Which means our
  generation (P) is required to be lower. We need to find acceptable P, given
  our reactances.
  * F = xb / (xa + xb) * P
  * F/P = xb / (xa + xb) -> P/F = (xa + xb) / xb
  * P = (xa + xb) / xb * F
  * Pmax = .5 / .2 * 126 (max capacity P) = 315 MW

* Now assume load Z buys generation from G2.
  * FIII: 3->2->1 = xb / xa+xb = .2 / (.3 + .2) * 200 = 2/5 * 200 = 80
  * FIV:  3->1    = xa / xa+xb = .3 / (.3 + .2) * 200 = 3/5 = 120 = 120

* If these flows are occurring simultaneously, we net out the flows (load Z
  generation is counter flow)
  * F1 - FIII = 160 - 80 = 80
  * FII - FIV = 240 - 120 = 120

* Idea here is contractual paths is not physical paths; point to point
  transmission rights don't necessarily work. This demonstrates that contracts
  and physics don't agree; it's not really about how to calculate flow. (Since
  anything larger than 3 bus can't just split up)

### Centralized Trading over Transmission Network (5.3)

* when losses and congestion in the transmission network are taken into account,
  the price of electrical energy depends on the bus where power is injected or
  extracted.
* Price consumers and producers pay/paid is the same for all participants
  connected to the same bus.

## DC-OPF as an Economic Problem: LMPs From Duals

* 2.2
* 5.3.2, 5.3.4

## PTDF and LODF: Topology Matrices

* 5.2
* 5.3.3, 5.3.5
* PyPSA

TODO: check other textbooks - there doesn't seem to be any PTDF directly
mentioned, LODF nothing
  * Wood/Wollenberg has math

## Fragility: Combining Duals with Topology

* 6.2.2
* 5.3.4

TODO: fragility isn't mentioned in textbook - where is this


## N-1 Contingency: LODF in Action

* 6 entire
* 6.4.2


## Boundary Conditions: Synthetic Grid to ERCOT Today

* 4.5, 4.5.3
* 3.4
* 3.5

## Basis and Validation

* 5.2.2
* 5.3.5


## End to End

* 1
