"""Guard direct internal imports across reviewed compatibility facades."""
from __future__ import annotations

import ast
from pathlib import Path


_FORWARDED_IMPORTS = {
    "compute.config": {"PG_DSN"},
    "compute.mu_forecast.panel.build": {
        "ERCOT_TZ",
        "DAM_CLOSE_HOUR",
        "dam_close",
        "history_cutoff",
        "delivery_day_of",
        "ct_day_bounds",
        "_dam_close_expr",
        "_vintage_cutoff_expr",
        "load_forecast_panel",
        "wind_forecast_panel",
        "solar_forecast_panel",
        "outage_panel",
        "calendar_features",
    },
    "compute.projection.propagate": {
        "MAP_RUN_ID",
        "MAX_SF_AGE_DAYS",
        "MIN_SF_COVERAGE",
        "load_forecast_sf",
        "load_window_sf",
        "resolve_sf_window",
        "sf_mass_coverage",
        "N_DRAWS",
        "band_metrics",
        "draw_congestion",
        "residual_pool",
        "DRIVERS_K",
        "DRIVERS_MAX_DAYS",
        "NodalPanel",
        "SfMuArtifact",
        "_NodalAccumulator",
        "build_sf_mu_artifact",
        "load_nodal",
        "load_sf_mu",
        "materialize_drivers",
        "node_contributions",
        "node_drivers",
        "parse_curated_days",
        "save_nodal",
        "save_sf_mu",
    },
}


def test_reviewed_compatibility_aliases_are_not_imported_indirectly():
    compute_dir = Path(__file__).parents[2]
    violations = []
    for path in compute_dir.rglob("*.py"):
        if path.name.startswith(".#"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            aliases = _FORWARDED_IMPORTS.get(node.module, set())
            imported = {name.name for name in node.names}
            indirect = sorted(imported & aliases)
            if indirect:
                violations.append(
                    f"{path.relative_to(compute_dir.parent)}:{node.lineno}: "
                    f"{node.module}: {', '.join(indirect)}")

    assert not violations, "\n".join(violations)
