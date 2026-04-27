import pandas as pd

def apply_operating_conditions(n,
                               p_max_pu_by_carrier=None,  # kept for backward compat
                               p_max_pu_per_gen=None, # series
                               loads=None,
                               outages=None,
                               line_derate=1.0,
                               tx_derate=1.0,
                               meta = None
                               ):

    """Mutate n in place to reflect boundary conditions."""
    # Loads: copy static values into time-series for the snapshot
    if loads is not None:
        load_vec = pd.Series(loads) if not isinstance(loads, pd.Series) else loads
        load_vec = load_vec.reindex(n.loads.index).fillna(n.loads['p_set'])
        n.loads['p_set'] = load_vec   # static — PyPSA uses this when loads_t is empty


    # Per-generator p_max_pu (new path — preferred)
    if p_max_pu_per_gen is not None:
        n.generators.loc[p_max_pu_per_gen.index, 'p_max_pu'] = p_max_pu_per_gen.values
    elif p_max_pu_by_carrier:
        # Backward-compat path for old hardcoded boundary conditions
            # Generator availability factors
        for carrier, cf in p_max_pu_by_carrier.items():
            mask = n.generators['carrier'] == carrier
            n.generators.loc[mask, 'p_max_pu'] = cf

    # Line derate
    if line_derate != 1.0:
        n.lines['s_nom'] = n.lines['s_nom'] * line_derate
    if tx_derate != 1.0:
        n.transformers['s_nom'] = n.transformers['s_nom'] * tx_derate

    # Outages: set s_nom to tiny value rather than 0 (avoids numerical issues)
    if outages:
        for line in outages:
            if line in n.lines.index:
                n.lines.loc[line, 's_nom'] = 1e-3

    # Lock capacity for operational dispatch
    n.generators['p_nom_extendable'] = False
    n.lines['s_nom_extendable'] = False

    # Patch zero-reactance lines (PTDF numerical stability)
    n.lines.loc[n.lines['r'] == 0, 'r'] = 1e-4
