"""Tests for scoreboard weekly split policy."""
from __future__ import annotations

from api.schemas.scoreboard import SourcePooled
from api.services.scoreboard import _beats_persistence


def _source(**metrics: float) -> SourcePooled:
    return SourcePooled(source="model", **metrics)


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
