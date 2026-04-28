# Snapshot Flow

* `snapshot.py` isolation

* `test_snapshot.py`
  * uses data, but doesn't persist output
  * OperatingDataAdaptor -> operating data
  * compute_snapshot

* `write_snapshots.py`
  * uses data
  * loads and writes to database
  * compute_one() ->
    * OperatingDataAdaptor -> operatingdata
    * compute_snapshot


## Definitions / Reminders

* MW: Real Power (P) - actual energy, turns on lights
* MVAr: Mega Volt-Amperes - Reactive Power (Q) - energy sloshing to and fro; for
  magnetic fields, not work
* MVA: Mega Volt-Amperes - Apparent Power (S) total -> S = sqrt(P^2 + Q^2)


* derate: a multiplier applied to thermal capacity `s_nom`. Model aging equipment, thermal effects.
  * `line_derate`: line
  * `tx_derate`: transmission
  * e.g 0.9, treat lines as having 90% capacity.

* Availability: fraction of nameplate capacity a generator can produce _right
  now_. Combines mechanical availability (not on outage) with resource
  availability (wind blowing, sun shining). Expressed [0, 1].
  * availability derate factor: % applied to reduce `p_max_pu` to represent
    ERCOT zonal/carrier type outage data.

* IRR: Intermittent Renewable Resource.
  * e.g. distinguish wind vs. solar
  * compared to say "Thermal Carriers": gas, coal, nuclear, etc.

* Pool: An aggregation of generators or resources treated as a group

* `p_max_pu`: PyPSA's per-unit max output for a generator at a given snapshot
  * % of how much each generator can dispatch, expressed as a fraction of its
    nameplate capacity. e.g. 500 MW gas generator with `p_max_pu = .90` can
    dispatch up to 450 MW, right now.
    * Allows a numerical fudging/mashing of availability per generator:
      * Resource Availability - e.g. wind/solar not blowing, cloudy day
      * Thermal: mechanical outage, maintenance
      * Battery: State of Charge proxy - how much energy remains in store to dispatch
      * Hydro: reservoir or flow availability
    * Separate capacity from availability

* `p_nom`: nameplate capacity of generator static MWh.
* `p_min_pu`: Per-unit minimum output, as a fraction of `p_nom` - sets generation floor.
* `p_max_pu`: Per-unit maximum output, as a fraction of `p_nom` - sets ceiling.
  Default of 1.0 is full capacity.
* `p_max_pu_per_gen` : pd.Series indexed by n.generators.index - sets `p_max_pu`
  per unit.
* `p_max_pu_per_carrier`: sets `p_max_pu` uniformly for all generators sharing a
  carrier (fuel type).

* SOC: State of Charge - how full a battery is.
  * e.g. 100 MW / 400 MWh battery = 100 MW power rating / 400 MWh energy
    capacity.
  * at 50% SOC has 200 MWh of energy: 400 MwH * .50 SOC = 200 MwH energy left.
  * 200 MwH energy / 100 Mw = 2 hours discharge.

* `p_set`: the setpoint - active power demand at a load, in MW
  * `n.loads['p_set']`: static - one value per load, no time
  * `n.loads_t.p_set` : time-series - pyPSA preferred, will fall back to static
    `p_set`, hence we had issue of no load appearing, and had to make sure loads
    were copied.
  * As this is run every data set hour, "static" ends up being time series of
    one-hour

* Dispatch: How much each generator is actually producing (MW) in the OPF
  solution. (`net.generators_t.p`)
* Load: Total electricity demand on the system at this snapshot - how much power
  consumers are pulling from grid right now.
* Flows: power flowing on each transmission line (MW), signed by direction (`net.lines_t.p0`)

* Objective Cost: The total system cost ($) the OPF minimized.

* `lmp`: Locational Marginal Price, $/MWh price at specific bus.
* `s_nom_`: apparent power capacity of a line in MVA
  * set to .001 MW to mimic a _line_ outage

* Binding constraint: line at its thermal limit; flow at `s_nom`
  * OPF want to send cheaper 700 MW across it but flow is capped at 500.
* shadow price (mu_upper / mu_lower)
  * zero shadow price, no binding constraint

* Binding lines = congestion; create LMP differences

* linopy: python linear optimization library (used in `n.optimize()`)
* HiGHS noise: actual LP/MIP solver (`solver="highs"`)


## Operating Adapter

* `run_snapshot_for_ts(ts, adapter, marginal_costs, NETWORK_PATH)`

  * `adapter = OperatingDataAdaptor()` -> (`__init__()`)
    * `_precompute()`: normalize and create lookups pd.Series from csv data
      * Normalize
        * lowercase: (`bus_zones.csv`): `ercot_zones`
        * lowercase: `generator_matches_enriched.csv` fields:
          * `bus` as str, `carrier`, `load_zone`, `pv_region`, `wind_region`
      * Generator lookup pd.Series: (bus, carrier, _field_)
        * TODO: gen_enriched to sum nameplate by zone: **Strong assumption
          Here** -> why can't we use nameplate data and/or weighting somehow to
          keep granularity or is it that unreliable?)
        * `gen_keyed` / `n_gens`: (bus, carrier) lookup + all metadata from network generators
        * Carrier -> nameplate (capacity_mw) lookups:  `pv_region`, `wind_region`, `lz_carrier`
      * Loads: from `network.loads['p_set']`, `network.loads['bus']`, loads by weather_zone, etc.
      * return `_Static` `@dataclass`; contains all the above pd.Series / dicts


  * `adapter.build()`:
    * query db by timestamp: load, wind, solar, outage
    * Remember enriched generator data from csv, (`gen_enriched`), to sum by
      carrier type (solar/wind) to get total nameplate capacity by region.

    * `p_max_pu = self._build_p_max_pu_per_gen(wind_row, solar_row)`
      * takes ERCOT data for wind (`_query_wind()`) and solar (`_solar_row()`)
      * calculates `p_max_pu` for each generator by zone (generation /
        nameplate), or use constant `DEFAULT_P_MAX_PU` for non-solar/non-wind

    * `outage_derates = self._derate_by_load_zone_carrier(outage_row)`
      * `allocate_pool()`: get availability factors by carrier type (IRR vs THERMAL)
      * populate `derates` dict: `{(zone, carrier_type): availability factor}`
        * e.g. `{ ('houston', 'solar'): 0.9841760369349914, ('houston',
          'battery'): 0.9841760369349914, ('north', 'wind'): 0.9370802984263757,
          ('north', 'solar'): 0.9370802984263757 . . .}`

    * `p_max_pu = self._apply_outages(p_max_pu, outage_derates)`
      * for each (load zone, carrier) generator group, filter to get a list of
        generator ids and multiply availability factors for new `p_max_pu` per
        generator.

    * `scale_loads(load_row)`: calcualte and apply an ERCOT scale factor to all
       TAMU model loads to keep shape of loads, but at ERCOT levels.

       * can't push real ERCOT zonal loads into TAMU buses, the spatial pattern
         probably won't match what TAMU's transmission topology can handle, and
         the OPF goes infeasible. Trade fidelity for feasibility - attempt to
         incorporate hourly load variation.

       * NB: Fragility calculation: recognize its not capturing load
         redistribution, but based on total load level (more load, more
         binding), generator availability, and outages.
         * TODO: decompose to zone level scale factor; ERCOT zone load / TAMU
           zone total

## Operating Conditions

* `apply_operating_conditions()`: all the data munging from OperatingDataAdapter
  and ERCOT data - apply it to input data for network calc.
  * loads copy over static values
  * apply calculated `p_max_pu_per_gen`: update `p_max_pu` per carrier, filter
    any missing generators
  * apply line derates
  * apply outages on lines (N-1)

## Snapshot Flow

* `snapshot.py:run_snapshot_for_ts()`:
  1. `adapter.build(ts)`
  2. `n = pypsa.Network(NETWORK_PATH)`
  3. `n.generators['marginal_cost']`
  4. `result = compute_snapshot()`

* `n`: PYPSA network
* `OperatingDataAdapter.build()`
* `compute_snapshot()`
  * `apply_operating_conditions()`
  * DC-OPF
  * PTDF-LODF
  * Fragility
  * N-1
  * Outputs:
    * lmp, dispatch, flows
  * Binding Constraints
    * shadow prices: mu_up, mu_lo
    * binding_lines filtered on .01 binding mask - TODO: what is .01 value


## Runtime Assumptions

* `operating_data`: assumptions per-unit fractions of nameplate capacity;
  `p_max_pu` is the ceiling on output for each carrier (% of `p_nom` - nameplate
  capacity).
  * e.g. wind: 20%, every wind generator produces at most 20% of installed capacity.

* OPF decided of that available capacity, how much to dispatch based on marginal cost.
  * e.g gas at 90%: up to 90% of gas generation is available, if optimizer needs it.

```
operating_data = {
  'p_max_pu_by_carrier': {
      'wind': 0.20,      # ERCOT wind typically 15-30% at peak
      'solar': 0.65,     # still producing but sun dropping
      'battery': 0.25,   # partial SOC, limited duration
      'nuclear': 0.95,
      'hydro': 0.50,
      'coal': 0.90,      # available but not forced on
      'gas': 0.90,
      'oil': 0.80,
      'biomass': 0.80,
      'other': 0.80,
  },
  ...
}

```


* Thermal carriers use hard-coded availability ceilings.

  * gas=0.90, coal=0.90, nuclear=0.95, hydro=0.50
  * `p_max_pu` is a ceiling on dispatchable output, not observed generation.
  * static even over timestamp (e.g solar at night)


* Battery's 0.25 `p_max_pu` is arbitrary.

ERCOT doesn't publish battery generation in NP4-745 or NP4-742.
The 0.25 is a SOC (state-of-charge) proxy, not a measured signal.


* Generators outside ERCOT footprint get `p_max_pu = 0`.

11 TAMU generators with `load_zone = 'non_ercot'` (SPP-served Panhandle,
Entergy-served East Texas, Rio Grande hydro on the Mexican border).
Topologically present in the network, but never dispatched.


* Line and transformer derates are 0.9 and 0.95 - set in (`OperatingDataAdapter`
  constructor)

* Renewable availability factors are uniform within each region.

Regional `gen_actual / nameplate` is applied to every generator in that region.

* Outage allocation is pooled by load zone and carrier class.

  * `total_mw_*` from `outages_zonal` allocates across thermal carriers
    (gas/coal/nuclear/oil/biomass/hydro)
  * `irr_mw_*` allocates across IRR carriers (wind/solar/battery)
  * `new_equip_mw_*` ignored (gen_matched is OP-status only)

Within each pool, derate is proportional to nameplate capacity. So gas, coal,
nuclear in West load zone get the same fractional derate, even though real
outages cluster on specific units.

* Load disaggregation uses TAMU's static distribution, scaled to ERCOT's hourly
  total.

Load gets: `n.loads['p_set'] * (ercot_hourly_total / tamu_static_total)`.
    * `n.loads`: TAMU load

Preserve TAMU's load shape while capturing ERCOT's temporal variation.


## Snapshot Tables

* `bus_snapshot`: (`interval_ts`, `bus_id`), `fragility`, `lmp`
  * collected in `write_snapshots.py` from `network.buses.index`
  * fragility/LMP per bus per hour

* `snapshot_meta`: per-snapshot OPF status, totals, JSONB diagnostics
