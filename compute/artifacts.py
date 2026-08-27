"""Canonical locations for artifacts scoped to a model run."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_RUNS_ROOT = Path(__file__).parent / "runs"


@dataclass(frozen=True)
class RunArtifacts:
    """Locations for the artifacts produced and consumed by one run."""

    run_id: str
    root: Path = DEFAULT_RUNS_ROOT

    @property
    def mu_dir(self) -> Path:
        return self.root / self.run_id / "mu"

    @property
    def forecast_dir(self) -> Path:
        return self.root / self.run_id / "forecast"

    @property
    def weekly_metrics(self) -> Path:
        return self.mu_dir / "mu_weekly.csv"

    @property
    def predictions(self) -> Path:
        return self.mu_dir / "mu_preds.npz"

    @property
    def scores(self) -> Path:
        return self.mu_dir / "mu_score_weekly.csv"

    @property
    def nodal_panel(self) -> Path:
        return self.forecast_dir / "mu_nodal.npz"
