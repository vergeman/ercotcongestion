import pypsa
import numpy as np
import pandas as pd

n = pypsa.Network("/data/processed/Texas2k_series25_case1_summerpeak.nc")

# Set a snapshot
n.set_snapshots([0])

#
# Apply marginal costs
# n.optimize() will use later for DC-OPF merit order dispatch.
#
marginal_costs = pd.read_csv("/data/processed/marginal_costs.csv", index_col=0)
n.generators['marginal_cost'] = n.generators.index.map(marginal_costs['marginal_cost'])


# Required before BODF/PTDF
# Identifies connected components — the network splits into "sub-networks" if
# there are islands. For Texas2k it's one big connected grid, so one
# sub-network. This must run before PTDF/BODF because they're computed per
# sub-network.

n.determine_network_topology()
sub = n.sub_networks.obj.iloc[0]

# Computes the matrix that answers: "if 1 MW is injected at bus i and withdrawn
# at the slack bus, how much of it flows through each line?"

sub.calculate_PTDF()
print(f"PTDF OK — shape: {sub.PTDF.shape}")

"""
BODF — Branch Outage Distribution Factor:
BODF is also called LODF in the literature, but PyPSA uses BODF

"if line c fails, how does the power it was carrying redistribute to other
lines?"

Line v. lines matrix: if a line fail how is power redistributed - what
fraction of X's flow now on line 0,1,2,3...
could invoke a cascading failure over capacity

---
Column X: effect of X failing on every line

BODF[0, X] = fraction of X's flow now on line 0
BODF[1, X] = fraction of X's flow now on line 1
BODF[2, X] = fraction of X's flow now on line 2
...
BODF[X, X] = -1  (X itself carries nothing)

---

Row b = how line b reacts to every other line's failure

BODF[b, 0] = effect on line b if line 0 fails
BODF[b, 1] = effect on line b if line 1 fails
BODF[b, 2] = effect on line b if line 2 fails
....
BODF[b, X] = effect on line b if line X fails



The diagonal is always -1 because the outaged line itself carries 0 after
outage (its original flow is redistributed away).
"""

sub.calculate_BODF()
print(f"BODF OK — shape: {sub.BODF.shape}")
print(f"BODF diagonal should be -1: {sub.BODF.diagonal()[:3]}")  # sanity check


"""
PTDF vs BODF


PTDF: sensitivity to injection changes (where power enters/leaves):

PTDF[line, bus] = "if I inject 1 MW at this bus and remove it at slack,
                   how much flows through this line?"

"If wind output drops 500 MW at this bus, which lines see increased flow?"
"If load grows in Houston, which corridors congest?"
"Which lines are sensitive to generator dispatch changes?"

The network topology doesn't change — you're just pushing different amounts of
power in/out of existing buses.


BODF: sensitivity to topology changes (line outages):

BODF[line_b, line_c] = "if line c fails entirely,
                        what fraction of its flow redistributes to line b?"

"If this line trips, where does its 500 MW go?"
"Which surviving lines might overload after N-1 outage?"

Topology-driven. The network structure changes — a line is removed.


Overloads: both can have overloads but from different causes:

* PDTF too much power pushed through existing topology
* BODF: lines can handle new (redistributed) flow after a line dies


Leads us to our notion of fragility and contingency:

* fragility = PTDF x shadow_price / headroom
* N-1 contingency: BODF

"""
