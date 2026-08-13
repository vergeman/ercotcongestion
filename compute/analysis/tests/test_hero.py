"""Pure hero slot and phrase-book tests; query tests land with hero_window."""
from compute.analysis.hero import (
    MAGNITUDE_RUNGS,
    classify_exceptions,
    classify_magnitude,
    classify_regime,
    classify_where,
    magnitude_verdict,
)
from compute.analysis.phrases import LADDERS, phrase_for, render


def test_magnitude_ladder_classifies_synthetic_daily_windows():
    prior = [100.0] * 27 + [160.0, 170.0, 180.0]
    cases = [
        (50.0, "quiet"), (100.0, "ordinary"), (130.0, "elevated"),
        (175.0, "near_top"),
    ]
    for value, expected in cases:
        slot = classify_magnitude({"value": value, "prior": prior,
                                   "basis": "artifact_keys", "n_keys": 32})
        assert slot["bucket"] == expected
        assert slot["n"] == 31

    record = classify_magnitude({"value": 201.0, "prior": prior,
                                 "basis": "artifact_keys", "n_keys": 32})
    assert record["bucket"] == "record_high" and record["rank"] == 1


def test_regime_where_and_exception_ladders_are_pure():
    regime = classify_regime({"series": "load.system", "today": 90, "median": 70,
                              "pct": 100, "n": 361, "basis": "forecast"})
    assert regime["bucket"] == "load_record_high" and not regime["reconcilable"]

    where = classify_where({"zone_shares": {"north": .44, "south": .56},
                            "geo_as_of": "2025-12-13"})
    assert where["bucket"] == "concentrated" and where["zone"] == "south"
    assert classify_where({"zone_shares": {"north": .511, "south": .489}})["bucket"] == "tilted"

    tier_0 = {"constraint_key": "NEW|ONE", "value": 30, "rank": 1, "n": 31}
    tier_1 = {"constraint_key": "TOP|TWO", "value": 20, "rank": 2, "n": 31}
    exceptions = classify_exceptions({"available": True, "tier_0": [tier_0], "tier_1": [tier_0, tier_1]})
    assert exceptions["bucket"] == "one_or_two"
    assert exceptions["count"] == 2
    assert exceptions["tier_0_count"] == 1 and exceptions["tier_1_count"] == 2
    assert exceptions["tier_1"][1] == tier_1
    assert classify_exceptions({"available": False}) == {"available": False, "bucket": "unavailable"}


def test_magnitude_verdict_is_rung_distance_not_a_new_threshold():
    forecast = {"bucket": "ordinary"}
    settled = {"bucket": "near_top"}
    assert magnitude_verdict(forecast, settled) == {"bucket": "under_called", "rungs": 2}
    assert MAGNITUDE_RUNGS.index("near_top") - MAGNITUDE_RUNGS.index("ordinary") == 2


def test_phrase_ladders_are_exhaustive_and_render_referenced_segments():
    for name, ladder in LADDERS.items():
        assert ladder[-1][0]({})

    slots = {
        "magnitude": {"bucket": "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "several", "count": 4, "tier_0_count": 1},
    }
    assert phrase_for("magnitude", slots["magnitude"])[0] == "ordinary"
    segments = render(slots)
    assert {part["ref"] for group in segments.values() for part in group} <= set(slots)
    assert all(part["text"] for group in segments.values() for part in group)
    assert "4 constraints outside the model vocabulary" in segments["lede"][2]["text"]
    assert "one is newly active" in segments["lede"][2]["text"]


def test_magnitude_adds_high_congestion_detail_only_for_a_material_rung_gap():
    slots = {
        "magnitude": {"bucket": "ordinary", "high_congestion_hours": {"bucket": "near_top"}},
        "regime": {"bucket": "ordinary"},
        "where": {"bucket": "distributed"},
        "exceptions": {"bucket": "none"},
    }
    headline = "".join(part["text"] for part in render(slots)["headline"])
    assert headline.endswith("; though high-congestion hours were near-record")
    slots["magnitude"]["high_congestion_hours"]["bucket"] = "elevated"
    assert len(render(slots)["headline"]) == 3
