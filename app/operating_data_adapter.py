"""
Operating data adapter: bridges ERCOT Postgres tables to compute_snapshot's
operating_data dict.

Architecture:
  __init__   -> precompute static metadata once (capacity matrices, load shares,
                generator-to-region maps)
  build(ts)  -> query 4 Postgres tables for the timestamp, translate to the
                dict shape that apply_operating_conditions consumes

Modeling assumptions (worth reading once before debugging):

1. Regional renewable factors are uniform within each region.
   NP4-742-CD reports wind by 5 regions, NP4-745-CD reports solar by 6 regions.
   Each generator inherits its region's availability factor:
     factor = region_actual_mw / region_nameplate_mw
   This means a wind farm in Panhandle gets the same factor as every other
   wind farm in Panhandle, even though their micro-meteorology differs.

2. Outage allocation pooling.
   outages_zonal reports MW out per LOAD ZONE in two buckets:
     - total_mw_*  : thermal/conventional outages (excludes IRR + new equip)
     - irr_mw_*    : intermittent renewable outages (wind+solar+battery)
     - new_equip_* : commissioning derates — IGNORED here (gen_matched is
                     EIA-860 OP-status only, so commissioning resources aren't
                     in our nameplate baseline anyway)
   We pro-rate each bucket across (load_zone, carrier) pairs in proportion to
   nameplate capacity. This implies:
     (a) Outages distribute uniformly within a load zone — wind farms in West
         are equally likely to be on outage when "West IRR" reports outages,
         even though real outages cluster.
     (b) Within IRR, wind/solar/battery share outage MW proportional to
         nameplate. Failure modes are unrelated in practice (a solar inverter
         fault doesn't predict a wind gearbox failure), so this is a modeling
         convenience, not a physical claim.

3. Outage timing: "what was known at time T."
   Most recent outages_zonal posting with posted_datetime <= ts and matching
   operating_date / hour_ending. Reflects what an operator would have seen,
   not the final-revision ground truth.

4. Thermal carriers don't get a live availability signal.
   gas/coal/nuclear/etc. keep their hardcoded DEFAULT_P_MAX_PU ceilings.
   They're dispatchable — p_max_pu represents an availability cap, not
   observed output. Outage derates from outages_zonal stack multiplicatively
   on top of these ceilings.

5. Generators outside ERCOT (load_zone = 'non_ercot') get p_max_pu = 0.
   These are TAMU placements in SPP / Eastern Interconnect. Topologically
   present in the network but not dispatched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row


# ============================================================================
# Constants
# ============================================================================

IRR_CARRIERS = ('wind', 'solar', 'battery')
THERMAL_CARRIERS = ('gas', 'coal', 'nuclear', 'oil', 'biomass', 'hydro')

# Carrier-level availability ceilings for non-renewable carriers
DEFAULT_P_MAX_PU: dict[str, float] = {
    'battery': 0.25,   # arbitrary SOC proxy — not a true availability signal
    'nuclear': 0.95,
    'hydro':   0.50,
    'coal':    0.90,
    'gas':     0.90,
    'oil':     0.80,
    'biomass': 0.80,
    'other':   0.80,
}

PV_REGIONS = ('centerwest', 'northwest', 'farwest', 'fareast', 'southeast', 'centereast')
WIND_REGIONS = ('panhandle', 'coastal', 'south', 'west', 'north')
LOAD_ZONES = ('houston', 'north', 'south', 'west')


# ============================================================================
# Adapter
# ============================================================================

@dataclass
class _Static:
    """Precomputed static metadata, built once at adapter construction."""
    # Per-network-generator metadata, indexed by n.generators.index
    gen_carrier:     pd.Series   # str
    gen_load_zone:   pd.Series   # str (one of LOAD_ZONES, or 'non_ercot')
    gen_pv_region:   pd.Series   # str | None  (lowercase)
    gen_wind_region: pd.Series   # str | None  (lowercase)

    # Region-level nameplate sums for availability factor calculation
    pv_region_nameplate:   dict[str, float]
    wind_region_nameplate: dict[str, float]

    # (load_zone, carrier) -> nameplate MW for outage pro-rating
    load_zone_carrier_nameplate: dict[tuple[str, str], float]

    # Per-load metadata for load disaggregation
    load_share:        pd.Series  # share within weather zone, sums to 1.0 per zone
    load_weather_zone: pd.Series  # str
    static_loads:      pd.Series  # TAMU's static p_set, indexed by n.loads.index
    static_total:      float      # sum of static_loads

    # Generators outside ERCOT — get p_max_pu = 0
    non_ercot_gens: pd.Index


class OperatingDataAdapter:
    """Build operating_data dicts for compute_snapshot from a UTC timestamp."""

    def __init__(
        self,
        conn: "psycopg.Connection",
        gen_enriched: pd.DataFrame,
        bus_zones: pd.DataFrame,
        network,
    ):
        """
        Parameters
        ----------
        conn : open psycopg connection
        gen_enriched : output of enrich_generators.py.
            Required columns: bus, carrier, capacity_mw,
            load_zone, pv_region, wind_region.
        bus_zones : bus_zones.csv. Required columns: name, ercot_zone.
        network : pypsa.Network. Used to read n.generators and n.loads.
        """
        self.conn = conn
        self._static = self._precompute(gen_enriched, bus_zones, network)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, ts: datetime) -> dict[str, Any]:
        """
        Build operating_data for a UTC timestamp.

        Returns
        -------
        dict with keys:
            'p_max_pu_per_gen' : pd.Series indexed by n.generators.index.
                                 Final per-generator availability factor,
                                 accounting for region availability x carrier
                                 defaults x outage derates x non-ERCOT zeroing.
            'loads'            : pd.Series indexed by n.loads.index, MW.
            'line_derate'      : float
            'tx_derate'        : float
            'meta'             : diagnostic dict
        """
        load_row   = self._query_load(ts)
        wind_row   = self._query_wind(ts)
        solar_row  = self._query_solar(ts)
        outage_row = self._query_outages(ts, load_row)

        p_max_pu = self._build_p_max_pu_per_gen(wind_row, solar_row)

        outage_derates = self._derate_by_load_zone_carrier(outage_row)
        p_max_pu = self._apply_outages(p_max_pu, outage_derates)

        if len(self._static.non_ercot_gens) > 0:
            p_max_pu.loc[self._static.non_ercot_gens] = 0.0

        loads = self._scale_loads(load_row)

        return {
            'p_max_pu_per_gen': p_max_pu,
            'loads': loads,
            'line_derate': 0.9,
            'tx_derate': 0.95,
            'meta': {
                'ts': ts,
                'load_total_mw': float(loads.sum()),
                'wind_factor_by_region': self._wind_factors(wind_row),
                'solar_factor_by_region': self._solar_factors(solar_row),
                'outage_posting_ts': outage_row['posted_datetime'] if outage_row else None,
            },
        }

    # ------------------------------------------------------------------
    # Precomputation
    # ------------------------------------------------------------------

    @staticmethod
    def _precompute(
        gen_enriched: pd.DataFrame,
        bus_zones: pd.DataFrame,
        network,
    ) -> _Static:
        # Normalize bus_zones (Title_Case -> lowercase)
        bz = bus_zones.copy()
        bz['ercot_zone'] = bz['ercot_zone'].astype(str).str.lower().str.replace(' ', '_')
        bus_to_weather_zone = dict(zip(bz['name'].astype(str), bz['ercot_zone']))

        # Normalize gen_enriched
        gen = gen_enriched.copy()
        gen['bus'] = gen['bus'].astype(str)
        gen['carrier'] = gen['carrier'].astype(str).str.lower()
        for col in ('load_zone', 'pv_region', 'wind_region'):
            if col in gen.columns:
                gen[col] = gen[col].where(gen[col].notna(), None)
                gen[col] = gen[col].apply(
                    lambda v: v.lower() if isinstance(v, str) else None
                )

        # Build per-(bus, carrier) lookup; collapse duplicates
        gen_keyed = gen.set_index(['bus', 'carrier'])
        gen_keyed = gen_keyed[~gen_keyed.index.duplicated(keep='first')]

        # For each network generator, look up its enriched metadata
        n_gens = network.generators[['bus', 'carrier']].copy()
        n_gens['bus'] = n_gens['bus'].astype(str)
        n_gens['carrier'] = n_gens['carrier'].astype(str).str.lower()

        def _lookup(row, col):
            try:
                v = gen_keyed.at[(row['bus'], row['carrier']), col]
                return v if pd.notna(v) else None
            except KeyError:
                return None

        gen_carrier     = n_gens['carrier']
        gen_load_zone   = n_gens.apply(lambda r: _lookup(r, 'load_zone'), axis=1)
        gen_pv_region   = n_gens.apply(lambda r: _lookup(r, 'pv_region'), axis=1)
        gen_wind_region = n_gens.apply(lambda r: _lookup(r, 'wind_region'), axis=1)

        # Default missing load_zone to 'non_ercot'
        gen_load_zone = gen_load_zone.fillna('non_ercot')

        # Region nameplate sums for renewable availability calculation
        pv_region_nameplate = (
            gen[(gen['carrier'] == 'solar') & gen['pv_region'].notna()]
            .groupby('pv_region')['capacity_mw']
            .sum()
            .to_dict()
        )
        wind_region_nameplate = (
            gen[(gen['carrier'] == 'wind') & gen['wind_region'].notna()]
            .groupby('wind_region')['capacity_mw']
            .sum()
            .to_dict()
        )

        # (load_zone, carrier) nameplate for outage allocation, ERCOT-only
        gen_in_ercot = gen[
            gen['load_zone'].notna() & (gen['load_zone'] != 'non_ercot')
        ]
        lz_carrier_nameplate = (
            gen_in_ercot
            .groupby(['load_zone', 'carrier'])['capacity_mw']
            .sum()
            .to_dict()
        )

        # Load disaggregation shares (within weather zone)
        loads_static = network.loads['p_set'].astype(float)
        load_bus = network.loads['bus'].astype(str)
        load_weather_zone = load_bus.map(bus_to_weather_zone)
        if load_weather_zone.isna().any():
            n_missing = int(load_weather_zone.isna().sum())
            raise ValueError(
                f"{n_missing} loads have no weather zone mapping. "
                f"Check that load bus values exist in bus_zones.csv 'name' column."
            )

        load_df = pd.DataFrame({
            'p_set': loads_static.values,
            'zone':  load_weather_zone.values,
        }, index=loads_static.index)
        zone_totals = load_df.groupby('zone')['p_set'].transform('sum')
        load_share = (load_df['p_set'] / zone_totals).where(zone_totals > 0, 0.0)

        # capture static loads and total for system-wide rescaling
        static_loads = loads_static.copy()
        static_total = float(loads_static.sum())

        non_ercot_gens = gen_load_zone.index[gen_load_zone == 'non_ercot']

        return _Static(
            gen_carrier=gen_carrier,
            gen_load_zone=gen_load_zone,
            gen_pv_region=gen_pv_region,
            gen_wind_region=gen_wind_region,
            pv_region_nameplate=pv_region_nameplate,
            wind_region_nameplate=wind_region_nameplate,
            load_zone_carrier_nameplate=lz_carrier_nameplate,
            load_share=load_share,
            load_weather_zone=load_weather_zone,
            static_loads=static_loads,
            static_total=static_total,
            non_ercot_gens=non_ercot_gens,
        )

    # ------------------------------------------------------------------
    # Postgres queries
    # ------------------------------------------------------------------

    def _query_load(self, ts: datetime) -> dict:
        sql = """
            SELECT operating_day, hour_ending,
                   coast, east, far_west, north, north_central,
                   south_central, southern, west, total
            FROM load_by_zone
            WHERE interval_ts = %s
            ORDER BY dst_flag ASC
            LIMIT 1
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts,))
            row = cur.fetchone()
        if row is None:
            raise LookupError(f"No load_by_zone row for interval_ts = {ts}")
        return row

    def _query_wind(self, ts: datetime) -> dict:
        sql = """
            SELECT gen_panhandle, gen_coastal, gen_south, gen_west, gen_north,
                   gen_system_wide
            FROM wind_hourly_regional
            WHERE interval_ts = %s
            ORDER BY dst_flag ASC
            LIMIT 1
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts,))
            row = cur.fetchone()
        if row is None:
            raise LookupError(f"No wind_hourly_regional row for interval_ts = {ts}")
        return row

    def _query_solar(self, ts: datetime) -> dict:
        sql = """
            SELECT gen_centerwest, gen_northwest, gen_farwest,
                   gen_fareast, gen_southeast, gen_centereast,
                   gen_system_wide
            FROM solar_hourly_regional
            WHERE interval_ts = %s
            ORDER BY dst_flag ASC
            LIMIT 1
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts,))
            row = cur.fetchone()
        if row is None:
            raise LookupError(f"No solar_hourly_regional row for interval_ts = {ts}")
        return row

    def _query_outages(self, ts: datetime, load_row: dict) -> dict | None:
        """Most recent posting <= ts for the operating_date / hour_ending of ts.

        load_row provides operating_day and hour_ending (already fetched in
        _query_load — passed in to avoid a second query).
        """
        op_date = load_row['operating_day']
        hour_ending = load_row['hour_ending']
        sql = """
            SELECT posted_datetime,
                   total_mw_south, total_mw_north, total_mw_west, total_mw_houston,
                   irr_mw_south,   irr_mw_north,   irr_mw_west,   irr_mw_houston
            FROM outages_zonal
            WHERE posted_datetime <= %s
              AND operating_date = %s
              AND hour_ending = %s
            ORDER BY posted_datetime DESC
            LIMIT 1
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts, op_date, hour_ending))
            row = cur.fetchone()
        return row

    # ------------------------------------------------------------------
    # Translation logic
    # ------------------------------------------------------------------

    def _wind_factors(self, wind_row: dict) -> dict[str, float]:
        out = {}
        for r in WIND_REGIONS:
            cap = self._static.wind_region_nameplate.get(r, 0.0)
            mw = wind_row.get(f'gen_{r}') or 0.0
            out[r] = max(0.0, min(1.0, mw / cap)) if cap > 0 else 0.0
        return out

    def _solar_factors(self, solar_row: dict) -> dict[str, float]:
        out = {}
        for r in PV_REGIONS:
            cap = self._static.pv_region_nameplate.get(r, 0.0)
            mw = solar_row.get(f'gen_{r}') or 0.0
            out[r] = max(0.0, min(1.0, mw / cap)) if cap > 0 else 0.0
        return out

    def _build_p_max_pu_per_gen(
        self,
        wind_row: dict,
        solar_row: dict,
    ) -> pd.Series:
        """Per-generator p_max_pu before outage derates and non-ERCOT zeroing."""
        wind_factors = self._wind_factors(wind_row)
        solar_factors = self._solar_factors(solar_row)

        out = pd.Series(index=self._static.gen_carrier.index, dtype=float)

        for gen_name in out.index:
            carrier = self._static.gen_carrier.loc[gen_name]
            if carrier == 'solar':
                region = self._static.gen_pv_region.loc[gen_name]
                out.loc[gen_name] = solar_factors.get(region, 0.0) if region else 0.0
            elif carrier == 'wind':
                region = self._static.gen_wind_region.loc[gen_name]
                out.loc[gen_name] = wind_factors.get(region, 0.0) if region else 0.0
            else:
                out.loc[gen_name] = DEFAULT_P_MAX_PU.get(carrier, 0.8)

        return out

    def _derate_by_load_zone_carrier(
        self,
        outage_row: dict | None,
    ) -> dict[tuple[str, str], float]:
        if outage_row is None:
            return {}

        derates: dict[tuple[str, str], float] = {}
        for lz in LOAD_ZONES:
            thermal_out = outage_row.get(f'total_mw_{lz}') or 0.0
            irr_out = outage_row.get(f'irr_mw_{lz}') or 0.0
            self._allocate_pool(derates, lz, irr_out, IRR_CARRIERS)
            self._allocate_pool(derates, lz, thermal_out, THERMAL_CARRIERS)
        return derates

    def _allocate_pool(
        self,
        derates: dict[tuple[str, str], float],
        load_zone: str,
        outage_mw: float,
        carriers: tuple[str, ...],
    ) -> None:
        if outage_mw <= 0:
            return
        pool_cap = sum(
            self._static.load_zone_carrier_nameplate.get((load_zone, c), 0.0)
            for c in carriers
        )
        if pool_cap <= 0:
            return
        for c in carriers:
            cap = self._static.load_zone_carrier_nameplate.get((load_zone, c), 0.0)
            if cap <= 0:
                continue
            allocated = outage_mw * (cap / pool_cap)
            derates[(load_zone, c)] = max(0.0, 1.0 - allocated / cap)

    def _apply_outages(
        self,
        p_max_pu: pd.Series,
        derates: dict[tuple[str, str], float],
    ) -> pd.Series:
        if not derates:
            return p_max_pu
        for (lz, carrier), derate in derates.items():
            mask = (
                (self._static.gen_load_zone == lz)
                & (self._static.gen_carrier == carrier)
            )
            p_max_pu.loc[mask] *= derate
        return p_max_pu


    def _scale_loads(self, load_row: dict) -> pd.Series:
        """Scale TAMU's static load distribution to match ERCOT's system total.

        Uses ERCOT's reported system total ('total' column in load_by_zone) as the
        target, and rescales TAMU's per-bus static loads uniformly. This preserves
        TAMU's spatial distribution (which the network was tuned for) while
        capturing ERCOT's hourly variation in total load.

        Trade-off: loses zonal fidelity (a load increase in West Texas in real
        life shows up everywhere proportionally rather than localized), but
        avoids infeasibilities from network mismatch with ERCOT's distribution.
        """
        ercot_total = load_row.get('total') or 0.0
        if ercot_total <= 0 or self._static.static_total <= 0:
            return pd.Series(0.0, index=self._static.static_loads.index)
        scale_factor = ercot_total / self._static.static_total
        return self._static.static_loads * scale_factor
