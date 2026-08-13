"""The hero phrase book.

Templates are intentionally separate from the slot classifiers.  Bucket names
are the stable API contract; changing the voice changes this file, not numeric
thresholds or frontend parsing.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


Slot = dict[str, Any]
Ladder = tuple[tuple[Callable[[Slot], bool], str, str], ...]


def _bucket(name: str) -> Callable[[Slot], bool]:
    return lambda slot: slot.get("bucket") == name


LADDERS: dict[str, Ladder] = {
    "magnitude": (
        (_bucket("record_high"), "record_high", "a record-high congestion day"),
        (_bucket("near_top"), "near_top", "a near-record congestion day"),
        (_bucket("elevated"), "elevated", "an elevated congestion day"),
        (_bucket("quiet"), "quiet", "a quiet congestion day"),
        (lambda _slot: True, "ordinary", "an ordinary congestion day"),
    ),
    "regime": (
        (_bucket("load_record_high"), "load_record_high", "system load is at a record high"),
        (_bucket("record_high"), "record_high", "conditions are at a record high"),
        (_bucket("near_record_high"), "near_record_high", "conditions are unusually high"),
        (_bucket("near_record_low"), "near_record_low", "conditions are unusually low"),
        (lambda _slot: True, "ordinary", "conditions are in their usual range"),
    ),
    "where": (
        (_bucket("concentrated"), "concentrated", "weight is concentrated in {zone}"),
        (_bucket("distributed"), "distributed", "weight is spread across zones"),
        (lambda _slot: True, "unknown", "the available geography is incomplete"),
    ),
    "exceptions": (
        (_bucket("several"), "several", "several exceptions stand apart"),
        (_bucket("one_or_two"), "one_or_two", "an exception stands apart"),
        (_bucket("unavailable"), "unavailable", "exceptions await DAM settlement"),
        (lambda _slot: True, "none", "no exceptions stand apart"),
    ),
}


def phrase_for(slot_name: str, slot: Slot) -> tuple[str, str]:
    """Return ``(bucket, text)`` from an ordered, exhaustive ladder."""
    for predicate, bucket, template in LADDERS[slot_name]:
        if predicate(slot):
            return bucket, template.format(**slot)
    raise AssertionError(f"{slot_name} phrase ladder is not exhaustive")


def render(slots: dict[str, Slot]) -> dict[str, list[dict[str, str]]]:
    """Render tooltip-ready text segments; callers never parse a flat string."""
    magnitude = phrase_for("magnitude", slots["magnitude"])[1]
    regime = phrase_for("regime", slots["regime"])[1]
    where = phrase_for("where", slots["where"])[1]
    exceptions = phrase_for("exceptions", slots["exceptions"])[1]
    return {
        "headline": [
            {"text": magnitude, "ref": "magnitude"},
            {"text": " — ", "ref": "where"},
            {"text": where, "ref": "where"},
        ],
        "lede": [
            {"text": regime, "ref": "regime"},
            {"text": "; ", "ref": "exceptions"},
            {"text": exceptions, "ref": "exceptions"},
            {"text": ".", "ref": "magnitude"},
        ],
    }
