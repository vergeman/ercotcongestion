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

from constants import (
    IRR_CARRIERS, THERMAL_CARRIERS, DEFAULT_P_MAX_PU,
    PV_REGIONS, WIND_REGIONS, LOAD_ZONES
)


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

    # Per-bus ERCOT LOAD_ZONE, indexed by network bus name (str).
    bus_load_zone: pd.Series


class OperatingDataAdapter:
    """Build operating_data dicts for compute_snapshot from a UTC timestamp."""

    def __init__(
        self,
        conn: "psycopg.Connection",
        gen_enriched: pd.DataFrame,
        bus_weather_zones: pd.DataFrame,
        network,
        line_derate=0.9,
        tx_derate=0.95
    ):
        """
        Parameters
        ----------
        conn : open psycopg connection
        gen_enriched : output of enrich_generators.py.
            Required columns: bus, carrier, capacity_mw,
            load_zone, pv_region, wind_region.
        bus_weather_zones : bus_weather_zones.csv. Required columns: name, ercot_weather_zone.
        network : pypsa.Network. Used to read n.generators and n.loads.
        line_derate :: float, default 0.9
            Multiplier applied to line thermal capacity (s_nom) in OPF.
        tx_derate :: float, default 0.95
            Multiplier applied to transformer thermal capacity (s_nom) in OPF.
        """
        self.conn = conn
        self._static = self._precompute(gen_enriched, bus_weather_zones, network)
        self.line_derate = line_derate
        self.tx_derate = tx_derate


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, ts: datetime) -> dict[str, Any]:
        """
        Build operating_data for a UTC timestamp.

        Returns
        -------
        dict with keys:
            'p_max_pu_per_gen'    : pd.Series indexed by n.generators.index.
                                    Final per-generator availability factor,
                                    accounting for region availability x carrier
                                    defaults x outage derates x non-ERCOT zeroing.
            'loads'               : pd.Series indexed by n.loads.index, MW.
            'line_derate'         : float
            'tx_derate'           : float
            'bus_load_zone'       : pd.Series, bus name -> ERCOT LOAD_ZONE
            'zonal_lmp_by_zone'   : dict[str, float | None], one entry per
                                    LOAD_ZONES key; 'None' when no data is
                                    available for ts.
            'meta'                : diagnostic dict
        """
        load_row   = self._query_load(ts)
        wind_row   = self._query_wind(ts)
        solar_row  = self._query_solar(ts)
        outage_row = self._query_outages(ts, load_row)
        zonal_lmp  = self._query_zonal_lmp(ts)

        p_max_pu = self._build_p_max_pu_per_gen(wind_row, solar_row)

        outage_derates = self._derate_by_load_zone_carrier(outage_row)
        p_max_pu = self._apply_outages(p_max_pu, outage_derates)

        if len(self._static.non_ercot_gens) > 0:
            p_max_pu.loc[self._static.non_ercot_gens] = 0.0

        loads = self._scale_loads(load_row)

        return {
            'p_max_pu_per_gen': p_max_pu,
            'loads': loads,
            'line_derate': self.line_derate,
            'tx_derate': self.tx_derate,
            'bus_load_zone': self._static.bus_load_zone,
            'zonal_lmp_by_zone': zonal_lmp,
            'meta': {
                'ts': ts,
                'load_total_mw': float(loads.sum()),
                'wind_factor_by_region': self._wind_factors(wind_row),
                'solar_factor_by_region': self._solar_factors(solar_row),
                'outage_posting_ts': outage_row['posted_datetime'] if outage_row else None,
                'outages_by_zone': self._outages_by_zone(outage_row)
            },
        }

    # ------------------------------------------------------------------
    # Precomputation
    # ------------------------------------------------------------------

    @staticmethod
    def _precompute(
        gen_enriched: pd.DataFrame,
        bus_weather_zones: pd.DataFrame,
        network,
    ) -> _Static:
        # Normalize bus_weather_zones (Title_Case -> lowercase)
        bz = bus_weather_zones.copy()
        bz['ercot_weather_zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
        bus_to_weather_zone = dict(zip(bz['name'].astype(str), bz['ercot_weather_zone']))

        # Per-bus ERCOT load zone
        # For basis computation: each bus's LMP subtracted against the zonal
        # LMP at its load zone hub.

        if 'ercot_load_zone' not in bz.columns:
            raise ValueError(
                "bus_weather_zones is missing 'ercot_load_zone' column; "
                "regenerate via preprocess/assign_bus_weather_load_zones.py"
            )
        bz['ercot_load_zone'] = (
            bz['ercot_load_zone']
            .where(bz['ercot_load_zone'].notna(), 'non_ercot')
            .astype(str).str.lower().str.replace(' ', '_')
        )
        bus_load_zone = pd.Series(
            bz['ercot_load_zone'].values,
            index=bz['name'].astype(str).values,
            name='bus_load_zone',
        )

        # Normalize gen_enriched
        gen = gen_enriched.copy()
        gen['bus'] = gen['bus'].astype(str)
        gen['carrier'] = gen['carrier'].astype(str).str.lower()
        for col in ('ercot_load_zone', 'pv_region', 'wind_region'):
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
        gen_load_zone   = n_gens.apply(lambda r: _lookup(r, 'ercot_load_zone'), axis=1)
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
            gen['ercot_load_zone'].notna() & (gen['ercot_load_zone'] != 'non_ercot')
        ]
        lz_carrier_nameplate = (
            gen_in_ercot
            .groupby(['ercot_load_zone', 'carrier'])['capacity_mw']
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
                f"Check that load bus values exist in bus_weather_zones.csv 'name' column."
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
            bus_load_zone=bus_load_zone
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

    def _query_zonal_lmp(self, ts: datetime) -> dict[str, float | None]:
        """Hourly-mean ERCOT zonal LMPs for ts, keyed by load zone.

        Reads ercot_zonal_lmp_hourly (view: hourly mean over the 15-min
        settlement-point prices). Returns one entry per LOAD_ZONES key;
        zones with no data for ts get None.

        """
        sql = """
            SELECT load_zone, lmp
            FROM ercot_zonal_lmp_hourly
            WHERE interval_ts = %s
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts,))
            rows = cur.fetchall()

        out: dict[str, float | None] = {z: None for z in LOAD_ZONES}
        for r in rows:
            zone = (r['load_zone'] or '').lower()
            if zone in out and r['lmp'] is not None:
                out[zone] = float(r['lmp'])
        return out

    # ------------------------------------------------------------------
    # Translation logic
    # ------------------------------------------------------------------

    def _outages_by_zone(self, outage_row: dict | None) -> dict | None:
        """Reshape a flat outage_row from outages_zonal into per-zone dicts.

        Returns None when no outage posting is available; persisted as JSONB
        null. Zone-level NULLs become 0.0 to keep the JSON well-formed on the
        read path.
        """
        if outage_row is None:
            return None

        out: dict[str, dict[str, float]] = {}
        for lz in ('south', 'north', 'west', 'houston'):
            out[lz] = {
                'thermal_mw': float(outage_row.get(f'total_mw_{lz}') or 0.0),
                'irr_mw':     float(outage_row.get(f'irr_mw_{lz}')   or 0.0),
            }
        return out

    # cap: total nameplate capacity
    # mw: ERCOT data
    # (capacity) factors: acutal / nameplate

    def _wind_factors(self, wind_row: dict) -> dict[str, float]:
        """
        Args: wind_row ERCOT data

        Example: {'gen_panhandle': 1441.2, 'gen_coastal': 2894.84, 'gen_south':
        2058.36, 'gen_west': 11490.06, 'gen_north': 1657.53, 'gen_system_wide':
        19541.99}

        Returns: factors: capacity % of nameplate
        (mw per region / mw nameplate capacity per region)

        Example: { 'panhandle': 0.2449312554171411, 'coastal':
        0.5338275429667331, 'south': 0.4407056909176551, 'west':
        0.5096884661961647, 'north': 0.5018863925392115}

        """
        out = {}
        for r in WIND_REGIONS:
            cap = self._static.wind_region_nameplate.get(r, 0.0)
            mw = wind_row.get(f'gen_{r}') or 0.0
            out[r] = max(0.0, min(1.0, mw / cap)) if cap > 0 else 0.0
        return out

    def _solar_factors(self, solar_row: dict) -> dict[str, float]:
        """
        Args: solar_region ERCOT data

        Example: {'gen_centerwest': 2371.73, 'gen_northwest': 2026.5,
        'gen_farwest': 2829.17, 'gen_fareast': 11384.61, 'gen_southeast':
        2579.81, 'gen_centereast': 3322.35, 'gen_system_wide': 24514.17}

        Returns: factors: capacity % of nameplate
        (mw per region / mw nameplate capacity per region)

        Example: {'centerwest': 0.6558443713187512, 'northwest':
        0.7624153498871332, 'farwest': 0.5411986379983166, 'fareast':
        0.8460745552103927, 'southeast': 0.7743689028965931, 'centereast':
        0.8216926767739222}

        """
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
        """
        Returns: Per-generator p_max_pu before outage derates and non-ERCOT zeroing.

        Lookup operational capacity, then build Series: matching generator
        name, and wind/solar/DEFAULT P_MAX_PU to get physical/operational
        availability for that hour [0, 1]

        Get acutal ERCOT data to capture generator availability by zone for solar/wind

        Example:

        name
        G0       0.509688  <- p_max_pu
        G1       0.541199
        G2       0.541199
        G3       0.541199
        G4       0.509688
           ...

        """
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
        """Args: outage_row; query from ERCOT gives total generation offline
        (IRR, THERMAL) by zone
        * IRR: renewables
        * THERMAL: gas, nuke, etc.

        Example:{..., 'total_mw_south': 9481.0, 'total_mw_north': 11497.0,
        'total_mw_west': 1446.0, 'total_mw_houston': 7489.0, 'irr_mw_south':
        1199.0, 'irr_mw_north': 996.0, 'irr_mw_west': 3057.0, 'irr_mw_houston':
        85.0}

        Need to figure out how to spread that across generators; or in this
        case zonal level of generation.

        Returns: {
          (zone x carrier): availability derate factors
        }

        Example:

        """

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
        """Goal: How do we split outage from a zone across types: proportional
        according to nameplate capacity

        Args:
        derates  : dict to be populated:
          * shape: {(load zone, carrier): availability factor}
        load_zone: EROCT's 4 load zones (hou, n,s, w)
        outage_mw: total outage by IRR or THERMAL carrier group
        carriers:  tuples of carrier types

        Returns: updates derates


        pool_cap = total nameplate capacity per load zone - sum across all
        carriers in (IRR or THERMAL)

        cap = single carrier's nameplate capacity for zone (e.g. 5000 gas)

        allocated = outage MW * cap / pool_cap

        proportion of outage assigned to carrier type in load zone.

         e.g. South gas = 25,000 / 50,000 (total all THERMAL) = 50% of thermal pool
              Outage of 1500MW in South; gas gets allocated 750MW.

        Populate derates with (zone, carrier) and availability factor

        derates[(zone, carrier)] = 1 - allocated / cap

        e.g. (South, gas) = 1 - 750 MW allocated / 25,000 MW (cap)
                          = 1 - 0.3
                          = .97

        97% of capacity is available, and 3% is derated.
        return per-unit availability multiplier
        """

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

        Args: load_row

        Example: {'operating_day': datetime.date(2026, 3, 25), 'hour_ending':
        18, 'coast': 16641.15, 'east': 2048.82, 'far_west': 8002.97, 'north':
        2378.65, 'north_central': 18716.61, 'south_central': 11419.08,
        'southern': 5427.2, 'west': 1839.0, 'total': 66473.48}

        ERCOT data total load / TAMU model load:

        scale factor = 66473.48 / 85758.89 = .77512

        Apply .775 factor to TAMU model to keep "shape" but scale to ERCOT
        data.

        """
        ercot_total = load_row.get('total') or 0.0
        if ercot_total <= 0 or self._static.static_total <= 0:
            return pd.Series(0.0, index=self._static.static_loads.index)

        scale_factor = ercot_total / self._static.static_total
        return self._static.static_loads * scale_factor
