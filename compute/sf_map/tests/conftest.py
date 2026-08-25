"""Shared fixtures for the sf tests."""
import numpy as np
import pandas as pd
import pytest

SEED = 0
N_HOURS = 500


def _spiky(rng, scale: float, bind_rate: float, n: int = N_HOURS) -> np.ndarray:
    """A shadow-price series: zero most hours, positive when binding.

    NP4-191 publishes binding rows only, so a constraint's μ is zero by
    construction on the hours it doesn't bind. The zeros are the majority of
    every column and they are what makes co-binding constraints collinear.
    """
    return np.clip(rng.normal(0, scale, n) * (rng.random(n) < bind_rate), 0, None)


@pytest.fixture
def planted():
    """A μ panel with known collinear structure. Returns (M, expected_blocks).

    * ``A0..A2`` — three constraints on one latent factor (a co-binding block).
    * ``B0, B1`` — near-perfectly collinear pair (B1 ≈ 2·B0).
    * ``C0``     — independent; must never merge.
    * ``D0, D1`` — *exactly* collinear (D1 = 3·D0); the degenerate case.
    * ``E_never``— never binds (zero variance).
    * ``F_thin`` — binds a single hour; too thin to correlate.
    """
    rng = np.random.default_rng(SEED)
    idx = pd.date_range("2025-01-01", periods=N_HOURS, freq="h", tz="UTC")

    zA = _spiky(rng, 300, 0.30)
    cols = {
        f"A{i}|C": zA * w + np.where(zA > 0, rng.normal(0, 5, N_HOURS), 0.0)
        for i, w in enumerate([1.0, 0.8, 1.3])
    }
    zB = _spiky(rng, 200, 0.25)
    cols["B0|C"] = zB
    cols["B1|C"] = zB * 2.0 + np.where(zB > 0, rng.normal(0, 0.5, N_HOURS), 0.0)
    cols["C0|C"] = _spiky(rng, 250, 0.30)
    zD = _spiky(rng, 150, 0.20)
    cols["D0|C"] = zD
    cols["D1|C"] = zD * 3.0
    cols["E_never|C"] = np.zeros(N_HOURS)
    thin = np.zeros(N_HOURS)
    thin[7] = 99.0
    cols["F_thin|C"] = thin

    expected = [
        {"A0|C", "A1|C", "A2|C"},
        {"B0|C", "B1|C"},
        {"C0|C"},
        {"D0|C", "D1|C"},
        {"E_never|C"},
        {"F_thin|C"},
    ]
    return pd.DataFrame(cols, index=idx), expected
