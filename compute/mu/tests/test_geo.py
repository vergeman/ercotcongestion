"""Constraint geography (plan/0088 commit 3).

Two acceptance criteria live here, and the second is the one that matters:

  * *"Centroid coverage reported as a fraction of binding μ-mass, not of key count."*
  * *"A test asserts the SF used for week w's geography was fit on a window ending
    at or before week w's refit start."*

**The leak this guards is the one the plan says will not look like a bug — it will
look like a result.** `SF` is fitted; fit it on all the data and every constraint's
geography knows the future. So the tests below plant that leak (a constraint whose
spatial signature only exists in the FUTURE) and demand the geography stay blind to
it. A leak test that never sees a leak is a test of nothing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.mu_forecast.geo import (constraint_geography, constraint_type,
                            coverage_by_mu_mass, geo_panel, haversine_km,
                            refit_grid, zone_anchors)


@pytest.fixture
def sp() -> pd.DataFrame:
    """Four settlement points, one per zone, at the corners of a rough Texas box."""
    return pd.DataFrame(
        {"lat": [29.76, 32.78, 27.80, 31.46],       # Houston, Dallas, Corpus, Midland
         "lon": [-95.37, -96.80, -97.40, -102.08],
         "zone": ["LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST"],
         "kv": [345.0, 138.0, 138.0, 345.0]},
        index=pd.Index(["HOU", "NOR", "SOU", "WES"], name="settlement_point"))


# ----------------------------------------------------------------- the centroid

def test_centroid_of_a_single_node_constraint_is_that_node(sp):
    """The degenerate case, which every weighting scheme must agree on."""
    SF = pd.DataFrame([[0.0, 0.9, 0.0, 0.0]], index=["A|c"], columns=sp.index)
    g = constraint_geography(SF, sp)
    assert g.loc["A|c", "geo_lat"] == pytest.approx(32.78)
    assert g.loc["A|c", "geo_lon"] == pytest.approx(-96.80)
    assert g.loc["A|c", "geo_zone_north"] == pytest.approx(1.0)
    assert g.loc["A|c", "geo_kv_mean"] == pytest.approx(138.0)
    assert g.loc["A|c", "geo_spread_km"] == pytest.approx(0.0)
    assert g.loc["A|c", "geo_sp_eff"] == pytest.approx(1.0)


def test_weights_are_absolute_so_an_opposing_pair_does_not_cancel(sp):
    """**The sign of a shift factor says which WAY, not WHERE.**

    A transmission constraint routinely pushes price up at one end and down at the
    other — that is what a constraint *is*. Weighting by signed SF would let those
    two ends cancel and put the centroid nowhere near either. Here two nodes carry
    equal and opposite SF: the centroid must land between them, and the zone shares
    must be 50/50, not 0.
    """
    SF = pd.DataFrame([[0.5, -0.5, 0.0, 0.0]], index=["A|c"], columns=sp.index)
    g = constraint_geography(SF, sp)

    assert g.loc["A|c", "geo_lat"] == pytest.approx((29.76 + 32.78) / 2)
    assert g.loc["A|c", "geo_zone_houston"] == pytest.approx(0.5)
    assert g.loc["A|c", "geo_zone_north"] == pytest.approx(0.5)
    assert g.loc["A|c", "geo_sp_eff"] == pytest.approx(2.0)
    assert g.loc["A|c", "geo_spread_km"] > 100     # they are ~360 km apart


def test_spread_separates_a_local_constraint_from_a_system_wide_one(sp):
    """The centroid ALONE cannot tell these apart, which is the whole reason
    `geo_spread_km` exists: mass split between Houston and Midland has a centroid
    in empty country, and the constraint lives in neither place."""
    local = pd.DataFrame([[0.9, 0.1, 0.0, 0.0]], index=["L|c"], columns=sp.index)
    wide = pd.DataFrame([[0.5, 0.0, 0.0, 0.5]], index=["W|c"], columns=sp.index)

    sl = constraint_geography(local, sp).loc["L|c", "geo_spread_km"]
    sw = constraint_geography(wide, sp).loc["W|c", "geo_spread_km"]
    assert sw > 3 * sl


def test_a_constraint_with_no_locatable_mass_gets_nan_not_a_fallback(sp):
    """A hole stays a hole — `build_panel`'s law. Filling this with the mean
    position would invent a location the market never implied."""
    SF = pd.DataFrame([[0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
                      index=["EMPTY|c", "REAL|c"], columns=sp.index)
    g = constraint_geography(SF, sp)
    assert g.loc["EMPTY|c"].isna().all()
    assert g.loc["REAL|c"].notna().any()


def test_unknown_settlement_points_are_ignored_not_guessed(sp):
    """SF columns we have no coordinates for (2.1% of the panel) contribute no
    weight, rather than dragging the centroid to (0, 0)."""
    SF = pd.DataFrame([[0.5, 0.0, 0.0, 0.0, 9.0]], index=["A|c"],
                      columns=list(sp.index) + ["MYSTERY_SP"])
    g = constraint_geography(SF, sp)
    assert g.loc["A|c", "geo_lat"] == pytest.approx(29.76)   # pure Houston


def test_haversine_is_a_real_distance():
    # Houston → Dallas is ~360 km. A flat-earth approximation is off by enough
    # to matter at Texas scale, so this pins the units as well as the formula.
    d = haversine_km(29.76, -95.37, 32.78, -96.80)
    assert 340 < float(d) < 380
    assert float(haversine_km(29.76, -95.37, 29.76, -95.37)) == pytest.approx(0.0)


def test_zone_anchors_are_derived_from_the_data_not_typed(sp):
    a = zone_anchors(sp)
    assert set(a.index) == {"LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "LZ_WEST"}
    assert a.loc["LZ_HOUSTON", "lat"] == pytest.approx(29.76)


# ------------------------------------------------ the type classifier (plan/0092)

def test_type_gtc_from_base_case_contingency():
    """The contingency component `BASE CASE` is a generic/interface constraint —
    always `gtc`, regardless of rail signature."""
    geo = pd.DataFrame({"n_rail": [3], "peak_offrail": [0.05]},
                       index=pd.Index(["X__A|BASE CASE"], name="constraint_key"))
    assert constraint_type(geo).loc["X__A|BASE CASE"] == "gtc"


def test_type_radial_is_a_rail_with_little_body():
    """A rail (n_rail>=1) with almost no graded body beneath it (peak_offrail<0.25)
    is a radial pocket/resource — one point."""
    geo = pd.DataFrame({"n_rail": [1], "peak_offrail": [0.10]},
                       index=pd.Index(["RES__G|SOME_LINE"], name="constraint_key"))
    assert constraint_type(geo).loc["RES__G|SOME_LINE"] == "radial"


def test_type_transmission_is_the_default():
    """A real line + real contingency with a graded body is transmission."""
    geo = pd.DataFrame({"n_rail": [0], "peak_offrail": [0.6]},
                       index=pd.Index(["LINE__1|OTHER_LINE"], name="constraint_key"))
    assert constraint_type(geo).loc["LINE__1|OTHER_LINE"] == "transmission"


def test_type_rail_with_a_real_body_is_not_radial():
    """A rail WITH a body beneath it (peak_offrail>=0.25) is a real radial resource
    on a live line, classified transmission — the radial label is reserved for the
    bare-pocket signature."""
    geo = pd.DataFrame({"n_rail": [1], "peak_offrail": [0.40]},
                       index=pd.Index(["BEL__G|LINE"], name="constraint_key"))
    assert constraint_type(geo).loc["BEL__G|LINE"] == "transmission"


# ------------------------------------------------------------ THE LEAK TRAP

def _panels(n_days: int = 120):
    """M and C consistent with C = −M·SFᵀ, for one constraint that only ever
    binds in the FIRST half of the window."""
    hours = pd.date_range("2025-01-01", periods=n_days * 24, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    M = pd.DataFrame({"A|c": 0.0, "B|c": 0.0}, index=hours)
    # A binds throughout; B binds ONLY in the last 30 days — the "future" half.
    M.loc[:, "A|c"] = np.where(rng.random(len(hours)) < 0.4, 50.0, 0.0)
    late = hours >= hours[0] + pd.Timedelta(days=n_days - 30)
    M.loc[late, "B|c"] = np.where(rng.random(int(late.sum())) < 0.6, 80.0, 0.0)

    sp_names = ["HOU", "NOR", "SOU", "WES"]
    SF_true = pd.DataFrame([[0.9, 0.1, 0.0, 0.0],     # A lives in Houston
                            [0.0, 0.0, 0.1, 0.9]],    # B lives in the West
                           index=["A|c", "B|c"], columns=sp_names)
    C = pd.DataFrame(-(M.to_numpy() @ SF_true.to_numpy()),
                     index=hours, columns=sp_names)
    C += rng.normal(0, 0.5, C.shape)
    return M, C


def test_geo_sf_window_ends_before_the_week(sp):
    """**THE acceptance test.** The SF behind a delivery day's geography must be
    fitted on a window that closed on or before that day.

    Constraint B does not exist until the last 30 days. A geography fitted globally
    would happily locate B in the West for *every* day in the panel, including days
    months before B ever bound — the future leaking backwards into a feature, and it
    would look like the model had learned where a constraint was before anyone could
    have known. Here, B must be unlocated (NaN) on every day whose SF window closed
    before B started binding.
    """
    M, C = _panels()
    days = pd.DatetimeIndex(sorted({d.normalize() for d in
                                    M.index.tz_convert("America/Chicago")
                                    .tz_localize(None)}))
    # A short window so several boundaries land inside the fixture.
    geo = geo_panel(M, C, days, sp=sp, window_days=30, refit_days=7, min_hours=5,
                    anchor=days[0])
    assert not geo.empty

    b_first_bind = (M.index[M["B|c"] > 0][0]
                    .tz_convert("America/Chicago").tz_localize(None).normalize())

    b = geo.xs("B|c", level="key", drop_level=True) if "B|c" in \
        geo.index.get_level_values("key") else pd.DataFrame()

    # Every day on which B IS located must be at least a day after B first bound —
    # it cannot be located by a window that had not yet seen it bind.
    located = b.index[b["geo_lat"].notna()] if len(b) else pd.DatetimeIndex([])
    assert (located > b_first_bind).all(), (
        "a constraint was located by an SF window that closed before it ever bound "
        "— the geography is reading the future")


def test_geo_of_a_scored_day_does_not_move_when_the_future_changes(sp):
    """The other face of the same knife, and the more direct statement of it.

    Take a delivery day, compute its geography, then **rewrite everything after it**
    — new constraint, different spatial signature, ten times the μ. Every `geo_*`
    value for that day must be byte-identical. If it moves, the feature is a function
    of data that had not happened yet.
    """
    M, C = _panels()
    days = pd.DatetimeIndex(sorted({d.normalize() for d in
                                    M.index.tz_convert("America/Chicago")
                                    .tz_localize(None)}))
    d = days[70]
    before = geo_panel(M, C, days[:71], sp=sp, window_days=30, refit_days=7,
                       min_hours=5, anchor=days[0]).xs(d, level="delivery_day")

    M2, C2 = M.copy(), C.copy()
    future = M2.index >= pd.Timestamp(d, tz="America/Chicago").tz_convert("UTC")
    M2.loc[future, "A|c"] = 500.0        # A goes wild, but only in the future
    C2.loc[future, "SOU"] = -900.0       # and its price signature moves elsewhere
    after = geo_panel(M2, C2, days[:71], sp=sp, window_days=30, refit_days=7,
                      min_hours=5, anchor=days[0]).xs(d, level="delivery_day")

    pd.testing.assert_frame_equal(before, after)


def test_refit_grid_covers_the_training_margin_and_keeps_the_scored_phase():
    """The grid is phase-locked to the first SCORED week, then extended backwards:
    the training margin needs geography too, and a grid that started at the first
    scored week would leave 240 days of training rows with none."""
    days = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    anchor = pd.Timestamp("2025-08-14")
    grid = refit_grid(days, refit_days=7, anchor=anchor)

    assert anchor in grid                       # phase preserved
    assert grid[0] <= days[0]                   # training margin covered
    assert ((grid - anchor) % pd.Timedelta(days=7) == pd.Timedelta(0)).all()


# --------------------------------------------------------------- coverage

def test_coverage_is_reported_in_mu_mass_not_key_count(sp):
    """**Key count flatters; μ-mass is what the score is made of.**

    One heavy constraint (located) and nine thin ones (not). By key count the arm
    covers 10%; by μ-mass it covers 99%. The acceptance criterion asks for the
    second number, and this pins that `coverage_by_mu_mass` returns it.
    """
    hours = pd.date_range("2025-06-01", periods=24, freq="h", tz="UTC")
    keys = ["BIG|c"] + [f"thin{i}|c" for i in range(9)]
    M = pd.DataFrame(0.0, index=hours, columns=keys)
    M["BIG|c"] = 100.0
    for k in keys[1:]:
        M[k] = 0.1

    day = pd.Timestamp("2025-06-01")
    geo = pd.DataFrame({"geo_lat": [29.0] + [np.nan] * 9},
                       index=pd.MultiIndex.from_product([[day], keys],
                                                        names=["delivery_day", "key"]))
    cov = coverage_by_mu_mass(M, geo, pd.DatetimeIndex([day]))

    assert cov.loc[0, "mass_located"] == pytest.approx(100 / (100 + 0.9), abs=1e-3)
    assert cov.loc[0, "keys_located"] == 1
    assert cov.loc[0, "keys_binding"] == 10
