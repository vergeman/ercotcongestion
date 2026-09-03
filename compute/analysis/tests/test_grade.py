import pandas as pd
import pytest

from compute.analysis.grade import (
    expected_average_precision,
    grade_profiles,
    top_fraction_labels,
)


def _profiles(rows: dict[str, list[float | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=pd.date_range("2026-07-28T05:00Z", periods=2, freq="h"))


def test_expected_average_precision_uses_expected_precision_inside_zero_score_ties():
    scores = pd.Series({"A": 1.0, "B": 0.0, "C": 0.0})
    bound = pd.Series({"A": True, "B": True, "C": False})

    # A is first; B is equally likely to be second or third in its tie, so its
    # expected precision is (2/2 + 2/3) / 2 and AP is their average.
    assert expected_average_precision(scores, bound) == pytest.approx(11 / 12)


def test_grade_uses_full_forecast_vocabulary_so_one_correct_call_cannot_hide_ten_misses():
    misses = {f"MISS{i}|BASE": [1.0, None] for i in range(10)}
    # The model vocabulary includes elements it priced at zero.  They are part
    # of the ranked pool, preventing the omitted settled binds from falling into
    # an all-positive tie and reading as a perfect forecast.
    model = _profiles({"RIGHT|BASE": [4.0, 0.0], **{f"QUIET{i}|BASE": [0.0, 0.0] for i in range(100)}})
    settled = _profiles({"RIGHT|BASE": [4.0, None], **misses})
    persistence = _profiles({})

    grade = grade_profiles(model, settled, persistence)

    assert len(grade.universe) == 111
    assert grade.model.detection_ap < 0.3
    assert grade.model.magnitude_overlap == pytest.approx(8 / 18)
    assert grade.model.timing_daily_skill < 0.2


def test_grade_keeps_a_settled_zero_as_a_bound_label():
    model = _profiles({"ZERO|BASE": [0.0, 0.0], "OTHER|BASE": [1.0, 0.0]})
    settled = _profiles({"ZERO|BASE": [0.0, None]})
    persistence = _profiles({})

    grade = grade_profiles(model, settled, persistence)

    assert grade.model.detection_ap == pytest.approx(0.5)
    assert grade.model.magnitude_overlap == pytest.approx(0.0)


def test_grade_keeps_prior_window_keys_in_the_explicit_scoring_universe():
    model = _profiles({"MODEL|BASE": [1.0, 0.0]})
    settled = _profiles({"SETTLED|BASE": [1.0, None]})
    persistence = _profiles({})

    grade = grade_profiles(model, settled, persistence, universe=["HISTORY|BASE"])

    assert grade.universe == ("MODEL|BASE", "SETTLED|BASE", "HISTORY|BASE")


def test_grade_exposes_persistence_on_every_prototype_metric():
    model = _profiles({"BOUND|BASE": [0.0, 3.0], "SPURIOUS|BASE": [1.0, 0.0]})
    settled = _profiles({"BOUND|BASE": [0.0, 3.0]})
    persistence = _profiles({"BOUND|BASE": [0.0, 3.0]})

    grade = grade_profiles(model, settled, persistence)

    assert grade.model.detection_ap == pytest.approx(1.0)
    assert grade.persistence.detection_ap == pytest.approx(1.0)
    assert grade.model.magnitude_overlap < grade.persistence.magnitude_overlap
    assert grade.model.timing_hourly_skill < grade.persistence.timing_hourly_skill


def test_grade_exposes_calibration_ceiling_and_event_rates_as_support():
    model = _profiles({"A|BASE": [1.0, 1.0]})
    settled = _profiles({"A|BASE": [2.0, 2.0]})
    persistence = _profiles({})

    grade = grade_profiles(model, settled, persistence)

    assert grade.support is not None
    assert grade.support.forecast_to_settled_ratio == 0.5
    assert grade.support.magnitude_ceiling == pytest.approx(2 / 3)
    assert grade.support.magnitude_of_ceiling == pytest.approx(1.0)
    assert grade.support.daily_bound_rate == 1.0
    assert grade.support.hourly_bound_rate == 1.0


def test_top_fraction_labels_use_stable_ties_at_the_cutoff():
    cols = [f"N{i}" for i in range(10)]
    labels = top_fraction_labels(
        pd.Series([10.0, 10.0, *range(8)], index=cols), 0.10
    )

    assert labels["N0"]
    assert not labels["N1"]
    assert labels.sum() == 1


def test_node_style_labels_score_ap_over_all_nodes_not_top_slice_capture():
    cols = [f"N{i}" for i in range(10)]
    model = pd.DataFrame([[10.0, 9.0, 8.0, *range(7)]], columns=cols)
    settled = pd.DataFrame([[9.0, 10.0, 8.0, *range(7)]], columns=cols)
    persistence = settled.copy()
    daily_bound = top_fraction_labels(settled.sum(axis=0), 0.10)
    hourly_bound = settled.apply(top_fraction_labels, axis=1, fraction=0.10)

    grade = grade_profiles(
        model,
        settled,
        persistence,
        daily_bound=daily_bound,
        hourly_bound=hourly_bound,
        hourly_skill="mean",
    )

    # The right node is second, so AP is 1/2 rather than the old zero capture.
    assert grade.model.detection_ap == pytest.approx(0.5)
    assert grade.model.timing_daily_skill == pytest.approx((0.5 - 0.1) / 0.9)
    assert grade.model.timing_hourly_skill == pytest.approx((0.5 - 0.1) / 0.9)
    assert grade.persistence.detection_ap == 1.0


def test_hourly_node_labels_are_selected_independently_each_hour():
    settled = pd.DataFrame(
        {
            "A": [10.0, 1.0],
            "B": [9.0, 10.0],
            **{f"N{i}": [0.0, 0.0] for i in range(8)},
        }
    )
    hourly_bound = settled.apply(top_fraction_labels, axis=1, fraction=0.10)

    assert hourly_bound.loc[0, "A"]
    assert hourly_bound.loc[1, "B"]
    assert hourly_bound.to_numpy().sum() == 2


def test_grade_rejects_profiles_that_do_not_share_target_delivery_hours():
    model = _profiles({"A|BASE": [1.0, 0.0]})
    settled = model.copy()
    persistence = model.copy()
    persistence.index = persistence.index + pd.Timedelta(days=1)

    with pytest.raises(ValueError, match="identical delivery-hour index"):
        grade_profiles(model, settled, persistence)
