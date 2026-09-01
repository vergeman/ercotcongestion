"""Pure bounded-axis selection policy for Matrix frames."""

from collections.abc import Callable

import pandas as pd


DEFAULT_ROW_LIMIT = 30
MAX_ROW_LIMIT = 100
MAX_COLUMN_LIMIT = 100
MAX_PINNED_ITEMS = 20
MAX_SEARCH_RESULTS = 20
ROW_PRESETS = {"top30": 30, "top100": 100, "pinned": 0}
DEFAULT_ANCHORS = [
    "HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_PAN",
    "LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST",
]
ANCHOR_REACH_EPS = 5e-4

ConstraintTypes = Callable[[list[str]], dict[str, str]]


def append_bounded(base: list[str], additions: list[str], *, limit: int) -> list[str]:
    result = list(base)
    for key in additions:
        if key not in result:
            result.append(key)
        if len(result) >= limit:
            break
    return result


def cursor_mu_abs(exact_mu, dam_by_key, keys) -> dict[str, float]:
    return {
        str(key): abs(dam) if (dam := dam_by_key.get(str(key))) is not None else abs(float(exact_mu.loc[key]))
        for key in keys
    }


def anchor_contribution_ranked(artifact, exact_mu, dam_by_key, anchors: list[str]) -> list[str]:
    if not anchors or artifact.SF.empty:
        return []
    anchor_abs = artifact.SF[anchors].abs()
    reach = anchor_abs.sum(axis=1)
    peak = anchor_abs.max(axis=1)
    cursor = cursor_mu_abs(exact_mu, dam_by_key, artifact.SF.index)
    scored = {
        str(key): cursor[str(key)] * float(reach.loc[key])
        for key in artifact.SF.index
        if float(peak.loc[key]) >= ANCHOR_REACH_EPS
    }
    return sorted(scored, key=lambda key: (-scored[key], key))


def default_hub_column(artifact, metadata, row_keys: list[str]) -> str | None:
    hubs = [str(sp) for sp in artifact.SF.columns if metadata.get(str(sp), (None, None))[0] == "hub"]
    if not hubs:
        return None
    if row_keys:
        reach = artifact.SF.loc[row_keys, hubs].abs().max(axis=0)
        return sorted(hubs, key=lambda sp: (-float(reach.loc[sp]), sp))[0]
    return hubs[0]


def select_constraints_major(
    artifact, ranked_rows, metadata, pinned_rows, pinned_columns,
    constraint_search, constraint_type, settlement_point_search, row_limit,
    column_limit, row_preset, column_set, constraint_types: ConstraintTypes,
):
    matched_rows = [key for key in ranked_rows if constraint_search and constraint_search in key.casefold()][:MAX_SEARCH_RESULTS]
    type_candidates = append_bounded(ranked_rows[:MAX_ROW_LIMIT], pinned_rows, limit=MAX_ROW_LIMIT + MAX_PINNED_ITEMS)
    type_candidates = append_bounded(type_candidates, matched_rows, limit=MAX_ROW_LIMIT + MAX_PINNED_ITEMS + MAX_SEARCH_RESULTS)
    row_types = constraint_types(type_candidates)
    core_reference_limit = row_limit if row_preset == "top30" else (DEFAULT_ROW_LIMIT if row_preset == "pinned" else ROW_PRESETS[row_preset])
    default_rows = ranked_rows[:core_reference_limit]
    core_max = artifact.SF.loc[default_rows].abs().max(axis=0)
    ranked_columns = [str(key) for key in sorted(artifact.SF.columns, key=lambda key: (-core_max.loc[key], str(key)))]
    base_rows = ranked_rows[:row_limit if row_preset == "top30" else ROW_PRESETS[row_preset]]
    if constraint_type:
        base_rows = [key for key in base_rows if row_types.get(key) == constraint_type]
    if constraint_search:
        base_rows = [key for key in base_rows if key in matched_rows]
    additions = [key for key in pinned_rows + matched_rows if key not in base_rows]
    row_keys = append_bounded([], base_rows, limit=MAX_ROW_LIMIT - len(additions))
    row_keys = append_bounded(row_keys, pinned_rows, limit=MAX_ROW_LIMIT)
    row_keys = append_bounded(row_keys, matched_rows, limit=MAX_ROW_LIMIT)
    if column_set == "anchors":
        base_columns = [key for key in ranked_columns if metadata.get(key, (None, None))[0] in {"hub", "load_zone"}][:column_limit]
    elif column_set == "default_anchors":
        base_columns = [sp for sp in DEFAULT_ANCHORS if sp in artifact.SF.columns]
    elif column_set == "pinned":
        base_columns = []
    else:
        base_columns = ranked_columns[:column_limit]
    matched_columns = [key for key in ranked_columns if settlement_point_search and settlement_point_search in key.casefold()][:MAX_SEARCH_RESULTS]
    if settlement_point_search:
        base_columns = [key for key in base_columns if key in matched_columns]
    if column_set == "pinned" and not pinned_columns and not settlement_point_search and not base_columns:
        if hub_seed := default_hub_column(artifact, metadata, row_keys):
            base_columns = [hub_seed]
    additions = [key for key in pinned_columns + matched_columns if key not in base_columns]
    column_keys = append_bounded([], base_columns, limit=MAX_COLUMN_LIMIT - len(additions))
    column_keys = append_bounded(column_keys, pinned_columns, limit=MAX_COLUMN_LIMIT)
    column_keys = append_bounded(column_keys, matched_columns, limit=MAX_COLUMN_LIMIT)
    return row_keys, column_keys, artifact.SF.loc[default_rows].abs().max(axis=0), row_types


def select_nodes_major(
    artifact, exact_mu, dam_by_key, pinned_rows, pinned_columns,
    settlement_point_search, row_limit, column_limit, constraint_types: ConstraintTypes,
):
    cursor = cursor_mu_abs(exact_mu, dam_by_key, artifact.SF.index)
    default_constraint = None if artifact.SF.empty else sorted((str(k) for k in artifact.SF.index), key=lambda key: (-cursor[key], key))[0]
    base_rows = list(pinned_rows) or ([default_constraint] if default_constraint else [])
    row_keys = append_bounded([], base_rows, limit=max(column_limit, 1))
    row_keys = append_bounded(row_keys, pinned_rows, limit=MAX_ROW_LIMIT)
    row_types = constraint_types(row_keys)
    node_score = artifact.SF.loc[row_keys].abs().max(axis=0) if row_keys else pd.Series(0.0, index=artifact.SF.columns)
    ranked_nodes = [str(key) for key in sorted(artifact.SF.columns, key=lambda key: (-float(node_score.loc[key]), str(key)))]
    matched_nodes = [key for key in ranked_nodes if settlement_point_search and settlement_point_search in key.casefold()][:MAX_SEARCH_RESULTS]
    base_nodes = ranked_nodes[:row_limit]
    if settlement_point_search:
        base_nodes = [key for key in base_nodes if key in matched_nodes]
    additions = [key for key in pinned_columns + matched_nodes if key not in base_nodes]
    column_keys = append_bounded([], base_nodes, limit=max(MAX_COLUMN_LIMIT - len(additions), 1))
    column_keys = append_bounded(column_keys, pinned_columns, limit=MAX_COLUMN_LIMIT)
    column_keys = append_bounded(column_keys, matched_nodes, limit=MAX_COLUMN_LIMIT)
    return row_keys, column_keys, node_score, row_types
