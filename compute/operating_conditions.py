import pandas as pd
from constants import DEFAULT_P_MAX_PU, SHED_PREFIX
import logging
logger = logging.getLogger(__name__)


def apply_static_mutations(
    n,
    line_derate: float = 1.0,
    tx_derate: float = 1.0,
    outages: list | None = None,
) -> None:
    """Mutate n in place with topology-static settings: derates, outages,
    capacity locks, and the zero-reactance numerical patch. Safe to call
    once per process; subsequent calls are idempotent for the same args.
    """
    if line_derate != 1.0:
        n.lines['s_nom'] = n.lines['s_nom'] * line_derate
    if tx_derate != 1.0:
        n.transformers['s_nom'] = n.transformers['s_nom'] * tx_derate

    # Outages: set s_nom to tiny value rather than 0 (avoids numerical issues).
    # Real line-level outage data does not exist for the TAMU↔ERCOT mapping,
    # so this path is stub-only; kept for N-1 contingency.
    if outages:
        for line in outages:
            if line in n.lines.index:
                n.lines.loc[line, 's_nom'] = 1e-3

    # Lock capacity for operational dispatch
    n.generators['p_nom_extendable'] = False
    n.lines['s_nom_extendable'] = False

    # Patch zero-reactance lines (PTDF numerical stability)
    n.lines.loc[n.lines['r'] == 0, 'r'] = 1e-4


def stack_time_varying(
    n,
    ts_list,
    op_by_ts: dict,
) -> None:
    """Populate n.loads_t.p_set and n.generators_t.p_max_pu with one row per
    ts in ts_list. Caller must have already called n.set_snapshots(ts_list).
    """
    other_default = DEFAULT_P_MAX_PU['other']

    load_rows = {}
    pmax_rows = {}
    for ts in ts_list:
        op = op_by_ts[ts]

        loads = op.get('loads')
        if loads is not None:
            load_vec = pd.Series(loads) if not isinstance(loads, pd.Series) else loads
            load_vec = load_vec.reindex(n.loads.index).fillna(n.loads['p_set'])
        else:
            load_vec = n.loads['p_set']
        load_rows[ts] = load_vec

        per_gen = op.get('p_max_pu_per_gen')
        if per_gen is None:
            raise ValueError(
                f"op_by_ts[{ts}] missing 'p_max_pu_per_gen' — adapter must "
                "supply per-generator availability"
            )
        missing = n.generators.index.difference(per_gen.index)
        shed_missing = missing[missing.str.startswith(SHED_PREFIX)]
        unexpected_missing = missing.difference(shed_missing)
        if len(unexpected_missing) > 0:
            logger.warning(
                f"{len(unexpected_missing)} generators escaped adapter coverage at {ts}, "
                f"using p_max_pu={other_default} fallback: {list(unexpected_missing)[:5]}..."
            )
        row = per_gen.reindex(n.generators.index)
        if len(shed_missing) > 0:
            row.loc[shed_missing] = 1.0
        pmax_rows[ts] = row.fillna(other_default)

    n.loads_t.p_set = pd.DataFrame(load_rows).T.reindex(columns=n.loads.index)
    n.loads_t.p_set.index.name = 'snapshot'

    n.generators_t.p_max_pu = (
        pd.DataFrame(pmax_rows).T.reindex(columns=n.generators.index)
    )
    n.generators_t.p_max_pu.index.name = 'snapshot'


def apply_operating_conditions(
    n,
    p_max_pu_per_gen=None,
    loads=None,
    outages=None,
    line_derate=1.0,
    tx_derate=1.0,
    bus_load_zone=None,
    zonal_lmp_by_zone=None,
    meta=None,
) -> None:
    """Single-snapshot helper used by experiment scripts in
    experiments/zonal_load/. Applies static mutations + sets static
    n.loads['p_set'] / n.generators['p_max_pu']. NOT for batched solves —
    use apply_static_mutations + stack_time_varying instead.

    bus_load_zone, zonal_lmp_by_zone, meta are ignored — kept in the
    signature so callers can spread an adapter op dict directly.
    """
    apply_static_mutations(
        n, line_derate=line_derate, tx_derate=tx_derate, outages=outages,
    )

    if loads is not None:
        load_vec = pd.Series(loads) if not isinstance(loads, pd.Series) else loads
        load_vec = load_vec.reindex(n.loads.index).fillna(n.loads['p_set'])
        n.loads['p_set'] = load_vec

    if p_max_pu_per_gen is not None:
        other_default = DEFAULT_P_MAX_PU['other']
        missing = n.generators.index.difference(p_max_pu_per_gen.index)
        shed_missing = missing[missing.str.startswith(SHED_PREFIX)]
        unexpected_missing = missing.difference(shed_missing)
        if len(unexpected_missing) > 0:
            logger.warning(
                f"{len(unexpected_missing)} generators escaped adapter coverage, "
                f"using p_max_pu={other_default} fallback: {list(unexpected_missing)[:5]}..."
            )
        full = p_max_pu_per_gen.reindex(n.generators.index)
        if len(shed_missing) > 0:
            full.loc[shed_missing] = 1.0
        full = full.fillna(other_default)
        n.generators['p_max_pu'] = full.values
