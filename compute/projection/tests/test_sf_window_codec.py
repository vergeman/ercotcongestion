import numpy as np
import pandas as pd
import pytest

from compute.projection.codecs import build_sf_window_artifact, load_sf_window_artifact


def test_sf_window_codec_round_trips_labels_shape_and_nan():
    sf = pd.DataFrame([[0.25, np.nan, -0.5]], index=["constraint/a"],
                      columns=["SP_A", "SP_B", "SP_C"])
    decoded = load_sf_window_artifact(build_sf_window_artifact(sf)).SF
    assert decoded.index.tolist() == ["constraint/a"]
    assert decoded.columns.tolist() == ["SP_A", "SP_B", "SP_C"]
    assert decoded.shape == (1, 3)
    np.testing.assert_allclose(decoded.to_numpy(), sf.to_numpy(), equal_nan=True)


def test_sf_window_codec_rejects_duplicate_labels_and_infinity():
    with pytest.raises(ValueError):
        build_sf_window_artifact(pd.DataFrame([[1], [2]], index=["c", "c"], columns=["sp"]))
    with pytest.raises(ValueError):
        build_sf_window_artifact(pd.DataFrame([[np.inf]], index=["c"], columns=["sp"]))
