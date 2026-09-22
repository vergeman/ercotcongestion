from compute.sf_map.storage import persist


def test_constraint_geo_persistence_imports_numpy():
    assert persist.np.isfinite(0)
