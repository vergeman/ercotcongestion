"""GET /matrix/frame — a bounded causal SF rectangle for one delivery hour."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from models import MatrixColumn, MatrixFrame, MatrixRow, MatrixSfValues
from services.sf_artifacts import load_daily_artifact, load_realized_mu


router = APIRouter(prefix='/matrix')

CENTRAL = ZoneInfo('America/Chicago')
DEFAULT_ROW_LIMIT = 30
DEFAULT_COLUMN_LIMIT = 40
MAX_ROW_LIMIT = 100
MAX_COLUMN_LIMIT = 100
MAX_PINNED_ITEMS = 20
MAX_SEARCH_RESULTS = 20
MAX_SEARCH_LENGTH = 64
ROW_PRESETS = {'top30': 30, 'top100': 100, 'pinned': 0}
# The canonical ERCOT anchors the SF-lens rotation set pins its node axis to —
# the settlement-hub prices and load-zone aggregates, in a stable display order.
# Only those present in the day's artifact are shown; the list is curated (not
# "every hub/zone"), so it excludes the *_AVG hubs and the minor load zones the
# 'anchors' column set would include.
DEFAULT_ANCHORS = [
    'HB_HOUSTON', 'HB_NORTH', 'HB_SOUTH', 'HB_WEST', 'HB_PAN',
    'LZ_HOUSTON', 'LZ_NORTH', 'LZ_SOUTH', 'LZ_WEST',
]
# A constraint whose peak |SF| over the shown anchors rounds to 0.000 has no
# visible interaction with the board — it is dropped from the default row
# ranking rather than shown as an all-blank row.
ANCHOR_REACH_EPS = 5e-4

# Metadata is deliberately best-effort: the artifact is authoritative for the
# matrix itself, and an absent topology record must not change its shape.
_SP_METADATA: dict[str, tuple[str | None, str | None]] | None = None


def _coerce_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _round_matrix_value(value: float) -> float:
    """The matrix UI renders these values to three decimal places."""
    return float(
        Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    )


def _delivery_date(ts: datetime):
    """ERCOT operating date, including the Central-time midnight boundary."""
    return _coerce_utc(ts).astimezone(CENTRAL).date()


def _split_constraint_key(key: str) -> tuple[str, str | None]:
    name, sep, contingency = str(key).partition('|')
    return name, contingency if sep else None


def _sp_metadata() -> dict[str, tuple[str | None, str | None]]:
    global _SP_METADATA
    if _SP_METADATA is None:
        # Keep this import local: pandas and the topology CSV are not needed to
        # resolve missing artifacts.
        from shared.settings import settings
        try:
            df = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            _SP_METADATA = {}
        else:
            _SP_METADATA = {
                str(r.settlement_point): (
                    None if pd.isna(getattr(r, 'sp_type', None)) else str(getattr(r, 'sp_type')),
                    None if pd.isna(getattr(r, 'load_zone', None)) else str(getattr(r, 'load_zone')),
                )
                for r in df.itertuples(index=False)
            }
    return _SP_METADATA


def _unavailable(run_id: str, delivery_date, interval_ts: datetime, reason: str) -> MatrixFrame:
    return MatrixFrame(
        available=False,
        unavailable_reason=reason,
        run_id=run_id,
        delivery_date=delivery_date,
        interval_ts=interval_ts,
        sf=MatrixSfValues(row_count=0, column_count=0, values=[]),
    )


def _bounded_values(values: list[str], *, name: str) -> list[str]:
    """Normalize repeated pin parameters before they reach dense selection."""
    normalized: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    if len(normalized) > MAX_PINNED_ITEMS:
        raise HTTPException(status_code=422, detail=f'{name} supports at most {MAX_PINNED_ITEMS} values.')
    return normalized


def _bounded_search(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_SEARCH_LENGTH:
        raise HTTPException(status_code=422, detail=f'{name} must be at most {MAX_SEARCH_LENGTH} characters.')
    return value.casefold() or None


def _append_bounded(base: list[str], additions: list[str], *, limit: int) -> list[str]:
    """Append discovery additions without changing the existing stable order."""
    result = list(base)
    for key in additions:
        if key not in result:
            result.append(key)
        if len(result) >= limit:
            break
    return result


def _constraint_types(cur, keys: list[str]) -> dict[str, str]:
    """Best-effort type metadata; absent map metadata must not change a frame."""
    if not keys:
        return {}
    cur.execute(
        "SELECT DISTINCT ON (constraint_key) constraint_key, ctype FROM constraint_geo "
        "WHERE constraint_key = ANY(%s) ORDER BY constraint_key, window_start DESC",
        (keys,),
    )
    return {str(r['constraint_key']): str(r['ctype']) for r in cur.fetchall() if r['ctype'] is not None}


def _dam_mu(cur, interval_ts: datetime, constraint_keys) -> dict[str, float]:
    """Exact-hour published DAM μ keyed exactly like the artifact vocabulary."""
    return load_realized_mu(cur, [interval_ts], constraint_keys).to_dict()


def _cursor_mu_abs(exact_mu, dam_by_key, keys) -> dict[str, float]:
    """Per-constraint \\|cursor μ\\|: published DAM μ at the hour where present,
    else the forecast μ. The ranking key for the SF-lens rotation set — "top
    constraints by ERCOT DAM μ, else forecast μ" — at the scrubbed hour."""
    out: dict[str, float] = {}
    for key in keys:
        dam = dam_by_key.get(str(key))
        out[str(key)] = abs(dam) if dam is not None else abs(float(exact_mu.loc[key]))
    return out


def _anchor_contribution_ranked(artifact, exact_mu, dam_by_key, anchors: list[str]) -> list[str]:
    """The SF-lens default row order for an anchor-columned board: constraints
    ranked by how much they drive the shown hubs/zones *at the cursor* —
    ``|μ_cursor| × Σ_anchors |SF|`` (μ_cursor = DAM μ where published, else
    forecast μ). Constraints with no visible reach into any anchor
    (peak \\|SF\\| < ``ANCHOR_REACH_EPS``) are dropped, so every displayed row has
    at least one non-zero cell — high μ alone never floats a blank row up."""
    if not anchors or artifact.SF.empty:
        return []
    anchor_abs = artifact.SF[anchors].abs()
    reach = anchor_abs.sum(axis=1)
    peak = anchor_abs.max(axis=1)
    cursor = _cursor_mu_abs(exact_mu, dam_by_key, artifact.SF.index)
    scored = {
        str(key): cursor[str(key)] * float(reach.loc[key])
        for key in artifact.SF.index if float(peak.loc[key]) >= ANCHOR_REACH_EPS
    }
    return sorted(scored, key=lambda key: (-scored[key], key))


def _default_hub_column(artifact, metadata, row_keys: list[str]) -> str | None:
    """The SF-lens column seed when no node is pinned yet (constraints view).

    Picks the hub settlement point with the largest max\\|SF\\| against the
    visible constraint rows, falling back to the first hub in the artifact when
    none score. Never invents a node: ``None`` when the artifact carries no hub.
    """
    hubs = [str(sp) for sp in artifact.SF.columns if metadata.get(str(sp), (None, None))[0] == 'hub']
    if not hubs:
        return None
    if row_keys:
        reach = artifact.SF.loc[row_keys, hubs].abs().max(axis=0)
        return sorted(hubs, key=lambda sp: (-float(reach.loc[sp]), sp))[0]
    return hubs[0]


def _select_constraints_major(
    cur, artifact, ranked_rows, metadata,
    pinned_rows, pinned_columns, constraint_search, constraint_type,
    settlement_point_search, row_limit, column_limit, row_preset, column_set,
):
    """Constraint-major selection: constraints are the primary (display-row) axis
    ranked by contribution; settlement points are the pinned/secondary columns.

    This is the established default; ``column_set == 'pinned'`` additionally seeds
    a single hub when the user has no node pins so the SF-lens grid opens
    non-empty. Returns ``(row_keys, column_keys, col_max, row_types)`` on the wire
    (rows=constraints, columns=nodes)."""
    matched_rows = [key for key in ranked_rows if constraint_search and constraint_search in key.casefold()][:MAX_SEARCH_RESULTS]
    # Preserve the established DAM/type discovery order; both use bounded key sets.
    type_candidates = _append_bounded(ranked_rows[:MAX_ROW_LIMIT], pinned_rows, limit=MAX_ROW_LIMIT + MAX_PINNED_ITEMS)
    type_candidates = _append_bounded(type_candidates, matched_rows, limit=MAX_ROW_LIMIT + MAX_PINNED_ITEMS + MAX_SEARCH_RESULTS)
    row_types = _constraint_types(cur, type_candidates)

    # Core columns always come from the frozen unfiltered row preset. Pins,
    # searches, and type filters may add or hide visible members but cannot
    # make the existing core columns jump around.  ``row_limit`` remains the
    # compatible form of the default top-30 preset.
    core_reference_limit = row_limit if row_preset == 'top30' else (DEFAULT_ROW_LIMIT if row_preset == 'pinned' else ROW_PRESETS[row_preset])
    default_rows = ranked_rows[:core_reference_limit]
    core_max = artifact.SF.loc[default_rows].abs().max(axis=0)
    ranked_columns = [str(key) for key in sorted(artifact.SF.columns, key=lambda key: (-core_max.loc[key], str(key)))]

    # Keep explicit row_limit compatible with the existing client while a preset
    # is top30; named presets use their fixed bounded universe.
    base_rows = ranked_rows[:row_limit if row_preset == 'top30' else ROW_PRESETS[row_preset]]
    if constraint_type:
        base_rows = [key for key in base_rows if row_types.get(key) == constraint_type]
    if constraint_search:
        base_rows = [key for key in base_rows if key in matched_rows]
    # Reserve bounded room for explicit pins and search matches, so a Top 100
    # request cannot make a pinned item disappear behind the cap.
    additions = [key for key in pinned_rows + matched_rows if key not in base_rows]
    row_keys = _append_bounded([], base_rows, limit=MAX_ROW_LIMIT - len(additions))
    row_keys = _append_bounded(row_keys, pinned_rows, limit=MAX_ROW_LIMIT)
    row_keys = _append_bounded(row_keys, matched_rows, limit=MAX_ROW_LIMIT)

    core_columns = ranked_columns[:column_limit]
    anchor_columns = [key for key in ranked_columns if metadata.get(key, (None, None))[0] in {'hub', 'load_zone'}]
    if column_set == 'anchors':
        base_columns = anchor_columns[:column_limit]
    elif column_set == 'default_anchors':
        # The curated ERCOT hubs/zones, in their canonical order, present in this
        # artifact — the stable node axis of the rotation set.
        base_columns = [sp for sp in DEFAULT_ANCHORS if sp in artifact.SF.columns]
    elif column_set == 'pinned':
        base_columns = []
    else:
        base_columns = core_columns
    matched_columns = [key for key in ranked_columns if settlement_point_search and settlement_point_search in key.casefold()][:MAX_SEARCH_RESULTS]
    if settlement_point_search:
        base_columns = [key for key in base_columns if key in matched_columns]
    # SF-lens default: seed a single hub when the pin-driven column axis is empty
    # and the user has neither pinned nor searched a node — so the grid opens
    # non-empty without inventing a node. The seed vanishes once a node is pinned.
    if column_set == 'pinned' and not pinned_columns and not settlement_point_search and not base_columns:
        hub_seed = _default_hub_column(artifact, metadata, row_keys)
        if hub_seed is not None:
            base_columns = [hub_seed]
    additions = [key for key in pinned_columns + matched_columns if key not in base_columns]
    column_keys = _append_bounded([], base_columns, limit=MAX_COLUMN_LIMIT - len(additions))
    column_keys = _append_bounded(column_keys, pinned_columns, limit=MAX_COLUMN_LIMIT)
    column_keys = _append_bounded(column_keys, matched_columns, limit=MAX_COLUMN_LIMIT)
    col_max = artifact.SF.loc[default_rows].abs().max(axis=0)
    return row_keys, column_keys, col_max, row_types


def _select_nodes_major(
    cur, artifact, exact_mu, dam_by_key,
    pinned_rows, pinned_columns, settlement_point_search, row_limit, column_limit,
):
    """Node-major selection: settlement points are the primary (display-row) axis
    ranked by \\|SF\\| reach against the shown constraints; constraints are the
    pinned/secondary columns seeded by the max-μ-at-cursor constraint.

    The wire stays constraint-major (rows=constraints, columns=nodes); the client
    transposes for display. ``column_limit`` bounds the constraint columns (wire
    rows), ``row_limit`` the node rows (wire columns). Returns
    ``(row_keys, column_keys, col_max, row_types)``."""
    # Constraint COLUMNS (wire rows): pins + the max-μ-at-cursor default seed,
    # preferring published DAM μ per constraint and falling back to forecast μ.
    def _cursor_mu(key) -> float:
        dam = dam_by_key.get(str(key))
        return abs(dam) if dam is not None else abs(float(exact_mu.loc[key]))

    default_constraint = None
    if not artifact.SF.empty:
        default_constraint = sorted((str(k) for k in artifact.SF.index), key=lambda k: (-_cursor_mu(k), k))[0]
    base_cols_c = list(pinned_rows)
    if not base_cols_c and default_constraint is not None:
        base_cols_c = [default_constraint]
    additions_c = [key for key in pinned_rows if key not in base_cols_c]
    row_keys = _append_bounded([], base_cols_c, limit=max(column_limit - len(additions_c), 1))
    row_keys = _append_bounded(row_keys, pinned_rows, limit=MAX_ROW_LIMIT)
    row_types = _constraint_types(cur, row_keys)

    # Node ROWS (wire columns): ranked by max|SF| against the chosen constraints,
    # the same reach signal the constraint-major ``core_max`` uses, on the other
    # axis; pins and search matches are force-included past the cap.
    if row_keys:
        node_score = artifact.SF.loc[row_keys].abs().max(axis=0)
    else:
        node_score = pd.Series(0.0, index=artifact.SF.columns)
    ranked_nodes = [str(key) for key in sorted(artifact.SF.columns, key=lambda key: (-float(node_score.loc[key]), str(key)))]
    matched_nodes = [key for key in ranked_nodes if settlement_point_search and settlement_point_search in key.casefold()][:MAX_SEARCH_RESULTS]
    base_nodes = ranked_nodes[:row_limit]
    if settlement_point_search:
        base_nodes = [key for key in base_nodes if key in matched_nodes]
    additions_n = [key for key in pinned_columns + matched_nodes if key not in base_nodes]
    column_keys = _append_bounded([], base_nodes, limit=max(MAX_COLUMN_LIMIT - len(additions_n), 1))
    column_keys = _append_bounded(column_keys, pinned_columns, limit=MAX_COLUMN_LIMIT)
    column_keys = _append_bounded(column_keys, matched_nodes, limit=MAX_COLUMN_LIMIT)
    return row_keys, column_keys, node_score, row_types


@router.get('/frame', response_model=MatrixFrame, summary='Bounded causal SF matrix frame')
def get_matrix_frame(
    interval_ts: datetime = Query(..., description='Delivery interval in ISO-8601 UTC.'),
    row_limit: int = Query(DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROW_LIMIT),
    column_limit: int = Query(DEFAULT_COLUMN_LIMIT, ge=1, le=MAX_COLUMN_LIMIT),
    row_preset: str = Query('top30', pattern='^(top30|top100|pinned)$'),
    constraint_type: str | None = Query(None, pattern='^(gtc|transmission|radial)$'),
    constraint_search: str | None = Query(None),
    settlement_point_search: str | None = Query(None),
    pinned_constraint: list[str] = Query(default=[]),
    pinned_settlement_point: list[str] = Query(default=[]),
    column_set: str = Query('core', pattern='^(core|anchors|pinned|core_pinned|default_anchors)$', description='Bounded named column selection.'),
    orientation: str = Query('constraints', pattern='^(constraints|nodes)$', description='Which axis gets the primary ranked/searched list treatment.'),
    row_order: str = Query('contribution', pattern='^(contribution|cursor_mu|anchor_contribution)$', description='Constraint row selection order: day contribution; |DAM μ| (else |forecast μ|) at the cursor; or anchor-restricted contribution (μ × reach into the shown anchors).'),
) -> MatrixFrame:
    pinned_constraint = _bounded_values(pinned_constraint, name='pinned_constraint')
    pinned_settlement_point = _bounded_values(pinned_settlement_point, name='pinned_settlement_point')
    constraint_search = _bounded_search(constraint_search, name='constraint_search')
    settlement_point_search = _bounded_search(settlement_point_search, name='settlement_point_search')
    interval_ts = _coerce_utc(interval_ts)
    # Artifacts are partitioned by their UTC timestamps.  The Central operating
    # date remains the response label, but must not select the artifact: its
    # first five summer hours otherwise look in the preceding UTC partition.
    delivery_date = _delivery_date(interval_ts)
    artifact_date = interval_ts.date()

    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=503, detail='no forecast run is published yet.')
        run_id = str(row['run_id'])

        artifact = load_daily_artifact(cur, run_id, artifact_date)
        if artifact is None:
            return _unavailable(run_id, delivery_date, interval_ts, 'artifact_missing')

        hour = pd.Timestamp(interval_ts)
        if hour not in artifact.E_mu.index:
            return _unavailable(run_id, delivery_date, interval_ts, 'interval_not_in_artifact')

        # Freeze default rows from the whole day, never from the selected hour. The
        # contribution mass is the artifact's causal μ multiplied by its recovered
        # SF reach; ties are explicit so refreshes cannot shuffle labels.
        mu_mass = artifact.E_mu.abs().sum(axis=0)
        reach = artifact.SF.abs().sum(axis=1)
        contribution = (mu_mass * reach).astype(float)
        sf_day_max_abs = float(artifact.SF.abs().to_numpy().max()) if not artifact.SF.empty else 0.0
        # For each row, its peak |μ| hour and peak-|SF| settlement point are
        # independently attainable, making this the exact day-wide maximum
        # absolute contribution in the recovered matrix.
        contribution_day_max_abs = float((artifact.E_mu.abs().max(axis=0) * artifact.SF.abs().max(axis=1)).max()) if not artifact.SF.empty else 0.0
        all_columns = [str(key) for key in artifact.SF.columns]
        pinned_rows = [key for key in pinned_constraint if key in artifact.SF.index]
        pinned_columns = [key for key in pinned_settlement_point if key in artifact.SF.columns]
        # Preserve the established DAM query before best-effort discovery
        # metadata; both use indexed, bounded key sets.
        dam_by_key = _dam_mu(cur, interval_ts, artifact.SF.index)
        metadata = _sp_metadata()
        exact_mu = artifact.E_mu.loc[hour]

        # Contribution ranking backs ``daily_rank`` and the universe counts no
        # matter how rows are selected; ``cursor_mu`` additionally re-orders which
        # constraints the bounded rows pick and their display order — the SF-lens
        # rotation set opens on the constraints with the largest |DAM μ| (else
        # |forecast μ|) at the scrubbed hour.
        contribution_ranked = [str(key) for key in sorted(artifact.SF.index, key=lambda key: (-contribution.loc[key], str(key)))]
        if row_order == 'anchor_contribution':
            anchors_present = [sp for sp in DEFAULT_ANCHORS if sp in artifact.SF.columns]
            ranked_rows = _anchor_contribution_ranked(artifact, exact_mu, dam_by_key, anchors_present)
        elif row_order == 'cursor_mu':
            cursor_abs = _cursor_mu_abs(exact_mu, dam_by_key, artifact.SF.index)
            ranked_rows = sorted((str(key) for key in artifact.SF.index), key=lambda key: (-cursor_abs[key], key))
        else:
            ranked_rows = contribution_ranked

        # The wire is always constraint-major (rows=constraints, columns=nodes).
        # ``orientation`` only chooses which axis is the ranked/searched primary
        # list; the client transposes ``nodes`` for display.
        if orientation == 'nodes':
            row_keys, column_keys, col_max, row_types = _select_nodes_major(
                cur, artifact, exact_mu, dam_by_key,
                pinned_rows, pinned_columns, settlement_point_search, row_limit, column_limit,
            )
        else:
            row_keys, column_keys, col_max, row_types = _select_constraints_major(
                cur, artifact, ranked_rows, metadata,
                pinned_rows, pinned_columns, constraint_search, constraint_type,
                settlement_point_search, row_limit, column_limit, row_preset, column_set,
            )
        row_sf = artifact.SF.loc[row_keys]

    rows: list[MatrixRow] = []
    matched_dam = 0
    daily_ranks = {key: rank for rank, key in enumerate(contribution_ranked, start=1)}
    for key in row_keys:
        name, contingency = _split_constraint_key(str(key))
        dam_mu = dam_by_key.get(str(key))
        matched_dam += dam_mu is not None
        rows.append(MatrixRow(
            constraint_key=str(key), constraint_name=name, contingency_name=contingency,
            constraint_type=row_types.get(str(key)),
            forecast_mu=_round_matrix_value(float(exact_mu.loc[key])), ercot_dam_mu=dam_mu,
            daily_rank=daily_ranks[str(key)],
            binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            max_abs_sf=_round_matrix_value(float(artifact.SF.loc[key].abs().max())),
        ))
    columns = [
        MatrixColumn(
            settlement_point=str(key), settlement_point_type=metadata.get(str(key), (None, None))[0],
            load_zone=metadata.get(str(key), (None, None))[1],
            max_abs_sf=_round_matrix_value(float(col_max.loc[key])),
        )
        for key in column_keys
    ]
    dam_status = 'available' if matched_dam == len(rows) else ('partial' if matched_dam else 'pending')
    values = [
        _round_matrix_value(float(value))
        for value in row_sf.loc[row_keys, column_keys].to_numpy().ravel()
    ]
    return MatrixFrame(
        available=True, run_id=run_id, delivery_date=delivery_date, interval_ts=interval_ts,
        dam_status=dam_status, rows=rows, columns=columns,
        rows_truncated=len(row_keys) < len(artifact.SF.index),
        columns_truncated=len(column_keys) < len(artifact.SF.columns),
        total_constraint_count=len(contribution_ranked), total_settlement_point_count=len(all_columns),
        sf_day_max_abs=sf_day_max_abs, contribution_day_max_abs=contribution_day_max_abs,
        orientation=orientation,
        sf=MatrixSfValues(row_count=len(rows), column_count=len(columns), values=values),
    )
