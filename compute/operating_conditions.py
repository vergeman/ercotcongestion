import pandas as pd
from constants import DEFAULT_P_MAX_PU
import logging
logger = logging.getLogger(__name__)


def apply_operating_conditions(n,
                               p_max_pu_by_carrier=None,  # kept for backward compat
                               p_max_pu_per_gen=None, # series
                               loads=None,
                               outages=None,
                               line_derate=1.0,
                               tx_derate=1.0,
                               bus_load_zone = None,
                               zonal_lmp_by_zone = None,
                               meta = None
                               ):

    """Mutate n in place to reflect boundary conditions."""
    #
    # Loads: copy static values into time-series for the snapshot
    #
    if loads is not None:
        load_vec = pd.Series(loads) if not isinstance(loads, pd.Series) else loads
        load_vec = load_vec.reindex(n.loads.index).fillna(n.loads['p_set'])
        n.loads['p_set'] = load_vec   # static — PyPSA uses this when loads_t is empty


    #
    # Per-generator p_max_pu (preferred)
    #
    if p_max_pu_per_gen is not None:
        # Adapter should already cover all gens via DEFAULT_P_MAX_PU.
        other_default = DEFAULT_P_MAX_PU['other']
        missing = n.generators.index.difference(p_max_pu_per_gen.index)
        if len(missing) > 0:
            # Hitting here means a generator escaped adapter coverage entirely.
            logger.warning(
                f"{len(missing)} generators escaped adapter coverage, "
                f"using p_max_pu=0.8 fallback: {list(missing)[:5]}..."
            )

        full = p_max_pu_per_gen.reindex(n.generators.index).fillna(other_default)
        n.generators['p_max_pu'] = full.values

    elif p_max_pu_by_carrier:
        # Backward-compat path for old hardcoded boundary conditions
        # Generator availability factors
        for carrier, cf in p_max_pu_by_carrier.items():
            mask = n.generators['carrier'] == carrier
            n.generators.loc[mask, 'p_max_pu'] = cf

    #
    # Line derate
    #
    if line_derate != 1.0:
        n.lines['s_nom'] = n.lines['s_nom'] * line_derate
    if tx_derate != 1.0:
        n.transformers['s_nom'] = n.transformers['s_nom'] * tx_derate

    #
    # Outages: set s_nom to tiny value rather than 0 (avoids numerical issues)
    # s_nom: set line to carry 0.001 MW
    #
    # NB: Don't have real line level data - outage data is on zone-based
    # generators and can't map TAMU to ERCOT at the line level.
    #
    # But keep for N-1 contingency
    if outages:
        for line in outages:
            if line in n.lines.index:
                n.lines.loc[line, 's_nom'] = 1e-3

    # Lock capacity for operational dispatch
    n.generators['p_nom_extendable'] = False
    n.lines['s_nom_extendable'] = False

    # Patch zero-reactance lines (PTDF numerical stability)
    n.lines.loc[n.lines['r'] == 0, 'r'] = 1e-4
