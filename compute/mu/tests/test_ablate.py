"""The ablation runner (plan/0088 commit 5).

The acceptance criteria this file carries:

  * *"The panel is built once; arms are selected by `--features` column-name prefix,
    and no arm refills a NaN."*
  * *"One table: all arms, both baselines, the pre-registered bars printed alongside."*

And the guard that makes the table mean anything: **the baselines cannot depend on
the arm.** Oracle, persistence, climatology and null are computed from `M`, `C` and
the SF map alone — the model's predictions never touch them. If persistence moves
between two arms, the arms were not scored on the same weeks or the same map, and
every comparison in the table is void. This project has had a refit grid silently
drift **twice**; this is the cheapest detector of that class of bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu.ablate import (ARMS, PERSISTENCE_TOPDEC, PRODUCT_TOPDEC,
                               check_baselines_identical, report)


def _scored(arm_topdec: dict[str, float], baseline_jitter: float = 0.0
            ) -> pd.DataFrame:
    """A scored frame in `score.py`'s shape: one row per (arm, source, week)."""
    weeks = pd.date_range("2025-08-14", periods=4, freq="7D", tz="UTC")
    rows = []
    for arm, td in arm_topdec.items():
        for w in weeks:
            rows.append({"arm": arm, "source": "model", "week": w, "regime": "all",
                         "pooled_r2": 0.2, "mae": 5.0, "rank_spearman": 0.5,
                         "sign_agree": 0.78, "topdecile_hit": td})
            for src, base_td in [("oracle", 0.762), ("persistence", 0.561),
                                 ("climatology", 0.455), ("null", np.nan)]:
                # `baseline_jitter` perturbs the baselines PER ARM — the bug this
                # guard exists to catch.
                bump = baseline_jitter if arm != ARMS[0] else 0.0
                rows.append({"arm": arm, "source": src, "week": w, "regime": "all",
                             "pooled_r2": 0.0, "mae": 9.0, "rank_spearman": 0.4,
                             "sign_agree": 0.7, "topdecile_hit": base_td + bump})
    return pd.DataFrame(rows)


# ------------------------------------------------- the harness is the control

def test_identical_baselines_pass():
    check_baselines_identical(_scored({a: 0.55 for a in ARMS}))


def test_a_baseline_that_moves_between_arms_voids_the_table():
    """**The whole table rests on this.** Persistence is computed from `M` alone and
    cannot know which features the model was given. If it moves, the arms were not
    scored on the same weeks or the same map — and an ablation whose control variable
    is drifting measures nothing. Refuse loudly rather than print a plausible table.
    """
    df = _scored({a: 0.55 for a in ARMS}, baseline_jitter=0.01)
    with pytest.raises(RuntimeError, match="baselines differ across arms"):
        check_baselines_identical(df)


def test_the_guard_tolerates_float_noise_but_not_a_real_difference():
    check_baselines_identical(_scored({a: 0.55 for a in ARMS},
                                      baseline_jitter=1e-12))
    with pytest.raises(RuntimeError):
        check_baselines_identical(_scored({a: 0.55 for a in ARMS},
                                          baseline_jitter=1e-6))


# ------------------------------------------------------- reading the two bars

def test_an_arm_between_the_bars_is_reported_as_alive_not_as_a_product():
    """**The single most important line of the report.**

    0.58 beats persistence (0.561) and fails §5.5 (0.60). The honest verdict is
    "we finally beat yesterday, and it is still not a product" — and the pressure to
    round that up to a win is exactly what `plan/s6-gate.md` was written to resist.
    """
    out = report(_scored({"base": 0.52, "lag": 0.58, "geo": 0.52,
                          "wx": 0.52, "all": 0.58}))
    lag = [ln for ln in out.splitlines() if "model:lag" in ln][0]
    assert "alive" in lag
    assert "PRODUCT" not in lag


def test_an_arm_that_clears_the_product_bar_says_so():
    out = report(_scored({"base": 0.52, "lag": 0.61, "geo": 0.52,
                          "wx": 0.52, "all": 0.61}))
    assert "PRODUCT" in [ln for ln in out.splitlines() if "model:lag" in ln][0]


def test_an_arm_that_loses_to_persistence_gets_no_verdict_at_all():
    out = report(_scored({a: 0.50 for a in ARMS}))
    base = [ln for ln in out.splitlines() if "model:base" in ln][0]
    assert "alive" not in base and "PRODUCT" not in base


def test_both_bars_are_printed_next_to_the_table():
    """The acceptance criterion says the pre-registered bars are printed alongside.
    A reader must not have to remember 0.561 and 0.60 — that is how a 0.56 gets
    talked into being a win."""
    out = report(_scored({a: 0.55 for a in ARMS}))
    assert str(PERSISTENCE_TOPDEC) in out
    assert str(PRODUCT_TOPDEC) in out
    assert "DIFFERENT questions" in out


def test_every_arm_and_both_baselines_appear_in_one_table():
    out = report(_scored({a: 0.55 for a in ARMS}))
    for arm in ARMS:
        assert f"model:{arm}" in out
    assert "persistence" in out and "oracle" in out


def test_attribution_is_stated_against_the_base_arm():
    """*"Attribution stated per arm. Which input worked?"* — the report must show
    each arm's delta over `base`, so "lagged μ did everything and the rest did
    nothing" is legible rather than buried in five absolute numbers."""
    out = report(_scored({"base": 0.50, "lag": 0.58, "geo": 0.50,
                          "wx": 0.501, "all": 0.58}))
    attrib = out.split("ATTRIBUTION")[1]
    assert "+0.080" in attrib      # lag carried it
    assert "+0.000" in attrib      # geo added nothing


def test_pre_and_post_rtcb_are_both_shown():
    """Pooled-only is not a read: the post-RTC+B half is where every forecast source
    falls apart, and an arm that improves only the pre half has not solved the live
    problem."""
    out = report(_scored({a: 0.55 for a in ARMS}))
    assert "PRE-RTC+B" in out and "POST-RTC+B" in out
