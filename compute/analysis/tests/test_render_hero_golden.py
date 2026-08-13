from collections import Counter
from datetime import date, timedelta

from compute.jobs import render_hero_golden as golden


def test_line_is_stable_text_and_keeps_every_slot_bucket():
    slots = {
        "magnitude": {"bucket": "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "several"},
    }
    line = golden.line_for(slots)
    assert line.startswith("magnitude=ordinary regime=load_record_high")
    assert "an ordinary congestion day" in line


def test_golden_rejects_a_dominant_ladder_bucket(monkeypatch):
    days = [(date(2026, 1, 1) + timedelta(days=i), 1) for i in range(3)]
    slots = {name: {"bucket": "ordinary"} for name in golden.SLOT_NAMES}
    slots["where"].update(zone="south")
    monkeypatch.setattr(golden, "build_hero", lambda *_: slots)
    try:
        golden.render_golden(None, "run", days)
    except ValueError as exc:
        assert "dominates golden" in str(exc)
    else:
        raise AssertionError("dominant bucket must fail golden generation")


def test_golden_renders_a_full_file_when_each_ladder_is_varied(monkeypatch):
    days = [(date(2026, 1, 1) + timedelta(days=i), 1) for i in range(4)]
    calls = Counter()

    def hero(*_args):
        i = sum(calls.values())
        calls["n"] += 1
        return {
            "magnitude": {"bucket": ("ordinary", "quiet")[i % 2]},
            "regime": {"bucket": ("ordinary", "near_record_high")[i % 2]},
            "where": {"bucket": ("distributed", "concentrated")[i % 2], "zone": "south"},
            "exceptions": {"bucket": ("none", "several")[i % 2]},
        }

    monkeypatch.setattr(golden, "build_hero", hero)
    lines = golden.render_golden(None, "run", days)
    assert len(lines) == 4 and lines[0].startswith("2026-01-01\t")
