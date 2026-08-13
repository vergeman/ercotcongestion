import pandas as pd
import pytest

from compute.analysis.grade import expected_average_precision, grade_profiles


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


def test_grade_can_use_a_separate_daily_event_definition_for_nodes():
    model = _profiles({"IMPORT": [0.2, 0.2], "EXPORT": [0.2, 0.2]})
    settled = _profiles({"IMPORT": [0.4, 0.4], "EXPORT": [0.4, 0.4]})
    persistence = _profiles({})
    hourly_bound = settled.abs().ge(0.3)
    daily_bound = settled.abs().mean(axis=0).ge(0.5)

    grade = grade_profiles(model.abs(), settled.abs(), persistence,
                           settled_bound=hourly_bound, settled_daily_bound=daily_bound)

    assert grade.model.detection_ap is None
    assert grade.model.timing_hourly_skill is None
    assert grade.model.magnitude_overlap == pytest.approx(2 / 3)


def test_grade_rejects_profiles_that_do_not_share_target_delivery_hours():
    model = _profiles({"A|BASE": [1.0, 0.0]})
    settled = model.copy()
    persistence = model.copy()
    persistence.index = persistence.index + pd.Timedelta(days=1)

    with pytest.raises(ValueError, match="identical delivery-hour index"):
        grade_profiles(model, settled, persistence)
