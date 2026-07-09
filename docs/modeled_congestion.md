# Modeled Congestion Notes

the ERCOT-side congestion signal for SP i in zone z at hour t is:
zone_local_spp[i, t] = SPP[i, t] − mean_{i' ∈ zone z}(SPP[i', t])

That's it. Simple per-zone demeaning per hour.

What it's actually doing conceptually. The premise is that ERCOT DAM SPPs share
a large regional common-mode price component. Every SP in Houston moves up and
down together with "Houston-ness" — same weather, same load pocket, same
import/export dynamics with the rest of the grid. That regional component isn't
congestion within Houston; it's Houston's collective position vs. the rest of
ERCOT. Subtracting the zonal mean strips that shared component and leaves what's
genuinely different about each SP relative to its zonal peers — which is the
intra-zone congestion signal you actually want to correlate against a model bus.
Concretely: if HB_HOUSTON, HB_HUBAVG's Houston children, and every Houston-area
LZ/RN node are all at $85/MWh in an hour where the rest of ERCOT is at $40, that
$85 has two components — the ~$40 system price and a ~$45 Houston-wide premium.
Neither is congestion at an individual Houston node. What is congestion at, say,
HB_BUSHILL is how much it deviates from the Houston mean in that hour — maybe
+$3 or −$2. That's what zone_local_spp isolates. Why this maps to the model side
cleanly. The model's kkt_perbus = Σ PTDF·μ already isolates per-bus congestion
contribution by construction — the LP dual math strips out the energy component
algebraically. So on the model side you already have "bus-level deviation from
what the system is doing generally." zone_local_spp is the ERCOT-side analog:
since you can't do the KKT math on real DAM prices (no line duals published),
you approximate by peer-group demeaning. The pairing kkt_perbus × zone_local_spp
is "model per-bus congestion residual vs. ERCOT per-SP zonal residual" — both
sides expressing the same physical idea (what's different about this location
vs. what its neighbors are doing) via the tool available on that side.


Why the "arithmetic mean, no weighting" choice is right here. You considered
load-weighting and rejected it. The load_weighted ablation confirmed that
instinct: load-weighting on the ERCOT side turned out to help under
Spearman/sign (recall sm × lw beat sm × sm), but only for a subtle reason
(better proxy for system energy price), and load-weighting on the model side
actively hurt. For zonal cancellation specifically, arithmetic mean is the right
choice — you're not trying to approximate a market price, you're computing "what
my zonal peers are doing on average," and no bus/SP deserves more vote than
another in defining the peer group. Two subtleties worth being aware of.

First, hub aggregators are excluded from the zone mean (HB_*) — good, they'd be
double-counting since hubs are themselves averages of their zonal children. But
verify: does the exclusion cover HB_HOUSTON, HB_NORTH, HB_SOUTH, HB_WEST,
HB_HUBAVG, HB_BUSAVG, HB_PAN? If any hub is silently included, it inflates the
zone mean toward that hub's own construction. Second, the four load zones are
unbalanced in SP count. West typically has fewer SPs than Houston or North.
Fewer SPs in a zone means the arithmetic mean has higher sampling variance per
hour, and any single outlying SP moves the whole zonal reference more. That's
part of why West showed the largest zonal residual std ($32.75 on ERCOT, $47.27
on model) in your Check A — smaller populations, noisier means. Not a bug, but
worth remembering when interpreting West's contribution to overall results.

What it is not doing. It's not zonal price-taker cancellation in the market
sense (which would use hub prices, not zone means). It's not a hub-basis
calculation (which would use HB_HOUSTON specifically as the reference). It's
specifically peer-group demeaning — subtracting the average behavior of your
zonal cohort from your own behavior. That's the right operation for revealing
intra-zone spatial congestion structure, and it's the operation that made 0072
work.

### Not Merit Order

Three distinct scalars, one per hour:

* merit_order — what you computed. Stack the whole fleet by cost, meet total
  load, ignore the transmission network entirely. This is the true uncongested
  counterfactual price. To get it you drop all line limits and re-clear.
* λ_energy (the OPF power-balance dual, = ERCOT's "system lambda") — the energy
  component inside the actual, congested solve. It's the uniform part of the
  LMPs — the price at the reference bus with all constraints active.
* congestion_bus — the bus-specific leftover: LMP_bus − λ_energy.

The thing you're missing: #1 and #2 are not equal when anything binds. "System
lambda" is not the uncongested price. It's the reference-bus energy price of the
congested solve. Why they differ. The LMP decomposition LMP_bus = λ_energy +
congestion_bus is an exact algebraic identity, but λ_energy in it is the dual of
the actual solve. When a line binds, the OPF has to redispatch around it — a
different unit sets the marginal price at the reference. So λ_energy moves off
merit_order. The gap λ_energy − merit_order is one scalar for the whole system
that hour, nonzero exactly when there's congestion.

Tiny example. No congestion: cheapest marginal unit is $30. merit_order = $30,
λ_energy = $30, they agree, every bus = $30, congestion = 0 everywhere. Now a
line binds and forces a $45 unit on at the reference to keep the balance
feasible: λ_energy = $45 (the actual solve says an extra MW costs $45), while
merit_order is still $30 (it never saw the line). A bus behind the constraint
might be $20. Its true congestion is 20 − 45 = −25. But if you subtract
merit_order you get 20 − 30 = −10 — wrong by $15, and that same $15 error lands
on every bus that hour. That per-hour, per-bus-uniform error is your 148
common-mode. So to answer directly: yes, ERCOT publishes a congested lambda. Its
system lambda is the SCED power-balance dual — definition #2. Your model side is
using definition #1. LMP − system_price = congestion is only true when
"system_price" is the congested energy dual (#2). Plug in the uncongested
counterfactual (#1) and you get congestion + (λ_energy − merit_order) — real
congestion plus a system-wide bias term. Which is why the fix is symmetry, not
"merit_order is buggy":

ERCOT side: SPP − system_lambda → uses the congested dual (#2). Correct.

Model side: use LMP − λ_OPF, the OPF's own power-balance dual — the same
definition. You already have it; it's −Σ PTDF·μ up to sign. Its bus-average is
~0 by construction, so the 148 std should collapse to ERCOT-like ~5.


The three λ's are not interchangeable:

* copper-plate / merit_order (~$10.45) — re-solve with congestion removed. This
  is the uncongested counterfactual. Cheap generation that was bottled up behind
  full lines is now free to serve, so the marginal unit is cheaper. This is a
  merit-order-flavored price.
* KKT clean-bus (~$26.68) ≈ slack LMP ($25.35) — LMP − ΣPTDF·μ, the uniform
  energy component of the actual congested solve.
* ERCOT system lambda — the SCED power-balance dual: the congested energy
  component. It equals the KKT concept, not copper-plate.


### Starting pair: kkt_perbus × zone_local_spp. Commit to it. Three reasons:

It has the strongest sign median (0.728) and most sign winners (73) of any pair.
Sign agreement is the axis regime conditioning is most likely to amplify — signs
sharpen dramatically in binding hours and get noisy in slack hours, which is
exactly the dilution pattern the regime handoff predicts.

If regime is real, this metric is where you'll see the biggest lift. It carries
the physical story on both sides. For the portfolio piece, "regime conditioning
improves the theoretically motivated reference" is a much stronger claim than
"regime conditioning improves an empirically discovered pair."

The former is a finding about grid physics; the latter is a finding about your
particular arithmetic. You've been carrying multiple candidates through three
handoffs. The cost has been real — every experiment gets doubled. Commit and
reclaim leverage.
