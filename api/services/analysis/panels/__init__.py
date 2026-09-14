"""Query-backed endpoints for the daily Brief's analysis panels.

Split into per-panel modules (0200); this package re-exports the flat surface
callers and ``brief.py`` still reach via ``panels.X``.
"""

from __future__ import annotations

# Re-exported resolution/hero helpers that brief.py composes via ``panels.X``.
from api.services.analysis.features.hero import get as get_hero
from api.services.analysis.resolution import (
    dam_landed as _dam_landed,
    resolve_delivery_date as _resolve_brief_delivery_date,
    resolve_horizon as _resolve_horizon,
    resolve_run as _resolve_run,
    selected_hours as _selected_hours,
)
from api.services.analysis.policy.comparison import joined_top_keys as _joined_top_keys

from api.services.analysis.panels._common import (
    MARKET_PEAK_CT_HOURS,
    MIN_STANDOUT_HISTORY_DAYS,
    NODE_CONGESTION_EPSILON,
    _resolve_or_unavailable,
    ranked,
    settled_history_stats,
)
from api.services.analysis.panels.catalog import (
    _constraint_geo,
    _structural_terms,
    _terms,
    get_constraints,
    get_node,
    get_settlement_points,
)
from api.services.analysis.panels.grade import (
    _brief_payload,
    get_grade,
    get_grade_history,
)
from api.services.analysis.panels.constraints import (
    _settled_constraint_history,
    _settled_standout_keys,
    _standout_rows,
    get_top_constraints,
)
from api.services.analysis.panels.nodes import (
    NodeContributions,
    _daily_node_contributions,
    _dominant_driver,
    _essp_canonical,
    _forecast_node_history,
    _node_standout_rows,
    _project_node_profile,
    _settled_node_history,
    _settled_node_standout_keys,
    _study_essp_groups,
    get_top_nodes,
)
from api.services.analysis.panels.context import _voltage_class, get_context
from api.services.analysis.panels.standouts import get_standouts
