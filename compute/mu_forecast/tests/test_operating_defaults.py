"""The shared SF operating point must reach every live μ/SF CLI."""
from __future__ import annotations

import argparse

import pytest

from compute.experiments.sf_out_of_window import common as frozen_oos
from compute.experiments.mu import feature_ablation as ablate
from compute.experiments.mu import outage_ablation as outage_ablate
from compute.experiments.sf import coverage as coverage_probe
from compute.jobs import weekly_map
from compute.mu_forecast import mu_model
from compute.sf_map import config


class _ParserCaptured(Exception):
    pass


def _defaults(monkeypatch, main) -> dict[str, object]:
    captured = {}

    def parse_args(parser, _argv=None):
        captured.update({action.dest: action.default for action in parser._actions})
        raise _ParserCaptured

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_args)
    with pytest.raises(_ParserCaptured):
        main([])
    return captured


def test_mu_aliases_share_the_sf_operating_point():
    assert mu_model.DEFAULT_TRAIN_DAYS is config.WINDOW_DAYS
    assert mu_model.DEFAULT_REFIT_DAYS is config.REFIT_DAYS
    assert coverage_probe.DEFAULT_WINDOW_DAYS is config.WINDOW_DAYS
    assert coverage_probe.DEFAULT_REFIT_DAYS is config.REFIT_DAYS
    assert coverage_probe.DEFAULT_MIN_HOURS is config.MIN_HOURS


@pytest.mark.parametrize(
    ("main", "window_name", "refit_name"),
    [
        (mu_model.main, "train_days", "refit_days"),
        (ablate.main, "train_days", "refit_days"),
        (outage_ablate.main, "train_days", "refit_days"),
        (coverage_probe.main, "window_days", "refit_days"),
        (weekly_map.main, "window_days", "refit_days"),
    ],
)
def test_map_and_mu_cli_defaults_match_the_operating_point(
        monkeypatch, main, window_name, refit_name):
    defaults = _defaults(monkeypatch, main)
    assert defaults[window_name] == config.WINDOW_DAYS
    assert defaults[refit_name] == config.REFIT_DAYS


def test_frozen_out_of_window_experiment_keeps_its_own_window():
    assert frozen_oos.WINDOW_DAYS == 60
    assert frozen_oos.REFIT_DAYS == 7
    assert frozen_oos.WINDOW_DAYS != config.WINDOW_DAYS


def test_coverage_probe_cli_admission_default_matches_the_operating_point(monkeypatch):
    assert _defaults(monkeypatch, coverage_probe.main)["min_binding_hours"] \
        == config.MIN_HOURS
