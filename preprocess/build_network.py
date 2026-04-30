import numpy as np, pypsa
from matpowercaseframes import CaseFrames
import pandas as pd
from pathlib import Path
from constants import EIA_TO_CARRIER
from shared.settings import settings

CASE_STEM = settings.case_stem
NETWORK_BUS_COORDS_CSV = settings.network_bus_coords_csv
NETWORK_GEN_FUELS_CSV = settings.network_gen_fuels_csv
NETWORK_SUBSTATIONS_CSV = settings.network_substations_csv
PROCESSED_DIR = settings.processed_dir
DATA_DIR = settings.data_dir

def enrich_network(n, case_dir):
    """Attach lat/lng coords, fuel, substation info from pre-extracted CSVs."""

    d = Path(case_dir)
    bus_coords = pd.read_csv(d / NETWORK_BUS_COORDS_CSV).set_index('bus')
    gens = pd.read_csv(d / NETWORK_GEN_FUELS_CSV)
    subs = pd.read_csv(d / NETWORK_SUBSTATIONS_CSV).set_index('sub')

    bus_ids = n.buses.index.astype(int)
    n.buses['x'] = bus_ids.map(bus_coords['lon']).values   # PyPSA convention: x=lon, y=lat expected for n.plot()
    n.buses['y'] = bus_ids.map(bus_coords['lat']).values
    n.buses['sub_id'] = bus_ids.map(bus_coords['sub']).values

    # Substation name (for aggregation/plotting)
    n.buses['sub_name'] = n.buses['sub_id'].map(subs['name'])

    # Fuel type → carrier. One gen per bus; adjust if multi-unit needed.
    fuel_by_bus = gens.drop_duplicates('bus').set_index('bus')['fuel']
    n.generators['carrier'] = (
        n.generators['bus'].astype(int)
        .map(fuel_by_bus)
        .replace(EIA_TO_CARRIER)   # uppercase codes → canonical names
        .str.lower()               # normalize any stragglers
        .fillna('unknown')
    )

def build_network(name, case_dir, case_stem):
    """
    Converts MATPOWER file to data frames (CaseFrames)
    Builds Python Power Case dict, imports into PyPSA to build network
    """
    d = Path(case_dir)

    cf = CaseFrames(str(d/ f"{case_dir}/{case_stem}.m"))   # parse MATPOWER -> Pandas DataFrames

    ppc = {
        # PYPOWER version set as 2
        "version": "2",

        # System base power (MVA: Mega Volt-Amperes) to convert per-unit values
        # to real units (div power quantities by 100 to normalize)
        "baseMVA": float(cf.baseMVA),

        # Bus Data Matrix
        # BUS_I     - Unique bus ID number
        # BUS_TYPE  - 1=PQ (load), 2=PV (generator), 3=slack/reference, 4=isolated
        # PD        - Real power load (MW)
        # QD        - Reactive power load (MVAr)
        # GS        - Fixed shunt conductance (MW at V=1 pu)
        # BS        - Fixed shunt susceptance (MVAr at V=1 pu)
        # BUS_AREA  - Area number for area interchange control
        # VM        - Bus voltage magnitude (per-unit)
        # VA        - Bus voltage angle (degrees)
        # BASE_KV   - Base voltage for per-unit conversion (kV)
        # ZONE      - Loss zone grouping
        # VMAX      - Upper voltage limit (per-unit)
        # VMIN      - Lower voltage limit (per-unit)
        # LAM_P     - Locational marginal price for real power ($/MWh) (OPF output)
        # LAM_Q     - Locational marginal price for reactive power ($/MVAr) (OPF output)
        # MU_VMAX   - Shadow price on Vmax constraint (OPF output)
        # MU_VMIN   - Shadow price on Vmin constraint (OPF output)
        "bus": cf.bus.values.astype(float),

        # Generator Data
        # GEN_BUS    - Bus number the generator is connected to
        # PG         - Real power output (MW)
        # QG         - Reactive power output (MVAr)
        # QMAX       - Upper reactive power limit (MVAr)
        # QMIN       - Lower reactive power limit (MVAr)
        # VG         - Voltage magnitude setpoint (per-unit)
        # MBASE      - Generator MVA base (usually = baseMVA)
        # GEN_STATUS - 1=in service, 0=out of service
        # PMAX       - Upper real power limit (MW)
        # PMIN       - Lower real power limit (MW)
        # PC1        - Lower real power of PQ capability curve point 1 (MW)
        # PC2        - Lower real power of PQ capability curve point 2 (MW)
        # QC1MIN     - Min reactive power at PC1 (MVAr)
        # QC1MAX     - Max reactive power at PC1 (MVAr)
        # QC2MIN     - Min reactive power at PC2 (MVAr)
        # QC2MAX     - Max reactive power at PC2 (MVAr)
        # RAMP_AGC   - Ramp rate for AGC (MW/min)
        # RAMP_10    - Ramp rate for 10-minute reserves (MW)
        # RAMP_30    - Ramp rate for 30-minute reserves (MW)
        # RAMP_Q     - Ramp rate for reactive power (MVAr/min)
        # APF        - Area participation factor for AGC dispatch
        # MU_PMAX    - Shadow price on Pmax constraint (OPF output)
        # MU_PMIN    - Shadow price on Pmin constraint (OPF output)
        # MU_QMAX    - Shadow price on Qmax constraint (OPF output)
        # MU_QMIN    - Shadow price on Qmin constraint (OPF output)
        "gen": cf.gen.values.astype(float),

        # Branch (line/transformer) data
        # F_BUS     - From bus number
        # T_BUS     - To bus number
        # BR_R      - Branch resistance (per-unit)
        # BR_X      - Branch reactance (per-unit)
        # BR_B      - Total branch charging susceptance (per-unit)
        # RATE_A    - MVA rating A, normal operation (MVA)
        # RATE_B    - MVA rating B, short-term operation (MVA)
        # RATE_C    - MVA rating C, emergency operation (MVA)
        # TAP       - Transformer off-nominal turns ratio (0 = no transformer)
        # SHIFT     - Transformer phase shift angle (degrees)
        # BR_STATUS - 1=in service, 0=out of service
        # ANGMIN    - Minimum angle difference F_BUS to T_BUS (degrees)
        # ANGMAX    - Maximum angle difference F_BUS to T_BUS (degrees)
        # PF        - Real power injected at from bus (MW) (power flow output)
        # QF        - Reactive power injected at from bus (MVAr) (power flow output)
        # PT        - Real power injected at to bus (MW) (power flow output)
        # QT        - Reactive power injected at to bus (MVAr) (power flow output)
        # MU_SF     - Shadow price on from bus MVA limit (OPF output)
        # MU_ST     - Shadow price on to bus MVA limit (OPF output)
        # MU_ANGMIN - Shadow price on ANGMIN constraint (OPF output)
        # MU_ANGMAX - Shadow price on ANGMAX constraint (OPF output)
        "branch": cf.branch.values.astype(float),

        # Generator
        # MODEL    - Cost model: 1=piecewise linear, 2=polynomial
        # STARTUP  - Startup cost ($)
        # SHUTDOWN - Shutdown cost ($)
        # NCOST    - Number of cost coefficients (polynomial) or data points (piecewise)
        # C3       - Cubic cost coefficient ($/MW^3)
        # C2       - Quadratic cost coefficient ($/MW^2)
        # C1       - Linear cost coefficient ($/MW)
        # C0       - Constant cost offset ($)
        "gencost": cf.gencost.values.astype(float) if hasattr(cf, "gencost") else np.zeros((len(cf.gen), 7)), # shape (len, 7)
    }

    n = pypsa.Network(name=name)
    n.import_from_pypower_ppc(ppc)  # NB: PYPOWER is a Python port of MATPOWER
    return n, ppc, cf


def describe_network(n):
    print(n)
    print(f"Buses: {len(n.buses)}")
    print(f"Lines: {len(n.lines)}, Transformers: {len(n.transformers)}")
    print(f"Generators: {len(n.generators)}, Loads: {len(n.loads)}")
    # PyPSA Network 'Texas2k Series 25'
    # Buses: 2751
    # Lines: 3993, Transformers: 1351
    # Generators: 1099, Loads: 1165

    # Add a snapshot (timestamp labeled 0) and try a power (load) flow
    #
    # Solves the AC power system equations - given known generation and load
    #
    #   Computes systems steady-state operating point
    #   Voltage magnitude / angle at every bus
    #   Real / reactive power flowing through every branch
    n.set_snapshots([0])
    n.pf()

    # Power Flow results
    print(n.buses_t.v_mag_pu.describe())          # Voltage magnitudes (should be ~0.95–1.05)
    print(n.lines_t.p0.abs().describe())          # Line flows in MW
    print(f"Total gen: {n.generators_t.p.sum(axis=1).iloc[0]:.0f} MW")
    print(f"Total load: {n.loads.p_set.sum():.0f} MW")

    # Separate PQ (load) buses from PV (gen) buses
    # PQ more vulnerable to voltage issues
    gen_buses = set(n.generators.bus)
    pq_buses = [b for b in n.buses.index if b not in gen_buses]

    v = n.buses_t.v_mag_pu.iloc[0]  # voltage at snapshot 0
    # NB: range on load buses - standard .95-1.05 acceptable voltage band
    print(f"PQ bus voltages: min={v[pq_buses].min():.3f}, max={v[pq_buses].max():.3f}")
    print(f"Buses below 0.95 pu: {(v < 0.95).sum()}") # buses under voltage
    print(f"Buses above 1.05 pu: {(v > 1.05).sum()}") # buses over votlage

    # Line loads at p0
    # power at the "from" end of each line - checks for heavy loaded lines
    flows = n.lines_t.p0.iloc[0].abs()
    print(f"Line flows: max={flows.max():.0f} MW, 95th pct={flows.quantile(0.95):.0f} MW")

    print(n.generators['carrier'].value_counts())                # fuel types
    print(n.buses[['x', 'y', 'sub_id', 'sub_name']].head())      # coordinates for substation
    print(f"Unique substations: {n.buses['sub_id'].nunique()}")  # num unique substations



if __name__ == '__main__':

    #n = pypsa.Network(name=name)
    #n.import_from_netcdf(f"{case_stem}.nc")

    n, ppc, cf = build_network(name="Texas2k Series 25",
                               case_dir=DATA_DIR/f"{CASE_STEM}",
                               case_stem=f"{CASE_STEM}")

    enrich_network(
        n,
        case_dir=DATA_DIR/f"{CASE_STEM}",
    )

    # Save so skip re-import
    out_file = str(PROCESSED_DIR/f"{CASE_STEM}.nc")
    n.export_to_netcdf(out_file)

    describe_network(n)


