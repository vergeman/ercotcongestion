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
        "net_load_regime",
        "candidate_keys",
        "_downcast_join",
        "_attach_refit_features",
        "audit_leakage",
    },
    "compute.projection.propagate": {
        "MAP_RUN_ID",
        "MAX_SF_AGE_DAYS",
        "MIN_SF_COVERAGE",
        "load_forecast_sf",
        "load_window_sf",
        "resolve_sf_window",
        "sf_mass_coverage",
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
    repo_dir = Path(__file__).parents[3]
    violations = []
    for package in ("api", "compute"):
        for path in (repo_dir / package).rglob("*.py"):
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
                        f"{path.relative_to(repo_dir)}:{node.lineno}: "
                        f"{node.module}: {', '.join(indirect)}")

    assert not violations, "\n".join(violations)


def test_serving_modules_do_not_import_backtest_orchestration():
    repo_dir = Path(__file__).parents[3]
    serving = (
        repo_dir / "compute/jobs/daily_forecast.py",
        repo_dir / "compute/jobs/backfill_forecasts.py",
    )
    for path in serving:
        modules = {
            node.module
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "compute.mu_forecast.model.backtest" not in modules
