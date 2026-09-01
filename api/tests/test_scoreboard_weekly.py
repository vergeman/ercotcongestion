"""Tests for scoreboard weekly split policy."""
from __future__ import annotations

from datetime import date

import pytest

from api.schemas.scoreboard import SourcePooled
from api.services.scoreboard import _beats_persistence, _build_splits, _split_rows


def _source(**metrics: float) -> SourcePooled:
    return SourcePooled(source_id="scoreboard_model_backtest_nodal", series_id="model", **metrics)


def test_beats_persistence_requires_all_three_screening_measures():
    """A model must win every gate metric, not merely a majority of them."""
    persistence = _source(
        rank_spearman=0.496,
        sign_agree=0.736,
        topdecile_hit=0.561,
    )
    model = _source(
        rank_spearman=0.548,
        sign_agree=0.787,
        topdecile_hit=0.523,
    )
    assert _beats_persistence(model, persistence) is False

    better = _source(
        rank_spearman=0.9,
        sign_agree=0.9,
        topdecile_hit=0.9,
    )
    assert _beats_persistence(better, persistence) is True


def test_splits_blend_live_days_by_hours_and_keep_cadence_counts():
    """A live day contributes one day's hours, not one backtest week's weight."""
    metrics = {
        "rank_spearman": 0.9,
        "sign_agree": 0.9,
        "topdecile_hit": 0.9,
    }
    weekly_rows = [
        {
            "week": date(2026, 7, 11),
            "source": "scoreboard_model_backtest_nodal",
            "n_hours": 168,
            **metrics,
        },
        {
            "week": date(2026, 7, 11),
            "source": "scoreboard_persistence_backtest_nodal",
            "n_hours": 168,
            **{key: 0.0 for key in metrics},
        },
    ]
    daily_rows = [
        {
            "delivery_date": date(2026, 7, 18),
            "source": "scoreboard_model_served_nodal",
            "n_hours": 24,
            **{key: 0.0 for key in metrics},
        },
        {
            "delivery_date": date(2026, 7, 18),
            "source": "scoreboard_persistence_prior_day_nodal",
            "n_hours": 24,
            **{key: 0.0 for key in metrics},
        },
    ]

    splits = {
        split.label: split
        for split in _build_splits(_split_rows(weekly_rows, daily_rows))
    }
    post = splits["post_rtc_b"]
    model = next(source for source in post.sources if source.series_id == "model")

    assert post.n_weeks == 1
    assert post.n_days == 1
    assert model.rank_spearman == pytest.approx(0.7875)
    assert post.beats_persistence is True
