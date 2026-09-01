from collections import Counter
from datetime import date, timedelta

from compute.analysis.hero_builder import HeroBuild
from compute.jobs import render_hero_golden as audit


def test_line_is_stable_text_and_keeps_every_slot_bucket():
    slots = {
        "magnitude": {"bucket": "ordinary"},
        "regime": {"bucket": "load_record_high"},
        "where": {"bucket": "concentrated", "zone": "south"},
        "exceptions": {"bucket": "several", "count": 3, "tier_0_count": 1},
    }
    line = audit.line_for(slots)
    assert line.startswith("magnitude=ordinary regime=load_record_high")
    assert "mag_rank=-/- mag_ratio=- regime_pct=- where_share=- tier_0=1 tier_1=0 exception_count=3" in line
    assert "An ordinary congestion day" in line


def test_audit_ignores_unavailable_slots_in_its_bucket_guard(monkeypatch):
    days = [(date(2026, 1, 1) + timedelta(days=i), 1) for i in range(3)]
    slots = {name: {"bucket": "ordinary"} for name in audit.SLOT_NAMES}
    slots["where"].update(zone="south")
    slots["exceptions"] = {"bucket": "none", "available": False}
    monkeypatch.setattr(audit, "build_hero", lambda *_a, **_k: HeroBuild(slots, None))
    try:
        audit.render_audit(None, "run", days)
    except ValueError as exc:
        assert "magnitude bucket dominates" in str(exc)
    else:
        raise AssertionError("available dominant buckets must fail audit")


def test_audit_renders_all_days_when_each_available_ladder_is_varied(monkeypatch):
    days = [(date(2026, 1, 1) + timedelta(days=i), 1) for i in range(4)]
    calls = Counter()

    def hero(*_args, **_kwargs):
        i = calls["n"]
        calls["n"] += 1
        return HeroBuild({
            "magnitude": {"bucket": ("ordinary", "quiet")[i % 2]},
            "regime": {"bucket": ("ordinary", "near_record_high")[i % 2]},
            "where": {"bucket": ("distributed", "concentrated")[i % 2], "zone": "south"},
            "exceptions": {"bucket": "pending", "available": False},
        }, None)

    monkeypatch.setattr(audit, "build_hero", hero)
    lines = audit.render_audit(None, "run", days)
    assert len(lines) == 4 and lines[0].startswith("2026-01-01\t")


def test_allow_dominant_records_the_override_in_the_written_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "available_days", lambda *_: [])
    monkeypatch.setattr(audit, "render_audit", lambda *_args, **_kwargs: ["2026-01-01\t..."])
    monkeypatch.setattr(audit.psycopg, "connect", lambda *_: _Connection())
    output = tmp_path / "audit.txt"
    assert audit.main(["--run-id", "run", "--end-date", "2026-01-01", "--output", str(output),
                       "--allow-dominant"]) == 0
    assert output.read_text().startswith("# audit_mode=allow_dominant")


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None
