"""Unit tests for the surviving SF projection primitives."""

import pandas as pd

from compute.analysis.brief import cell_contributions, nodal_congestion


def test_cell_contributions_and_nodal_congestion_share_the_sign_convention():
    sf = pd.DataFrame(
        {"IMPORTER": [-0.8, -0.6], "EXPORTER": [0.8, 0.6]},
        index=["A|B", "C|D"],
    )
    mu = pd.Series({"A|B": 10.0, "C|D": 20.0})

    cells = cell_contributions(sf, mu)

    assert cells.to_dict() == {
        "IMPORTER": {"A|B": 8.0, "C|D": 12.0},
        "EXPORTER": {"A|B": -8.0, "C|D": -12.0},
    }
    assert nodal_congestion(sf, mu).to_dict() == {"IMPORTER": 20.0, "EXPORTER": -20.0}
