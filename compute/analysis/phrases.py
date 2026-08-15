"""The hero phrase book.

Templates are intentionally separate from the slot classifiers.  Bucket names
are the stable API contract; changing the voice changes this file, not numeric
thresholds or frontend parsing.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from compute.analysis.hero import MAGNITUDE_RUNGS


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
        (_bucket("ordinary_low"), "ordinary_low", "a quieter-than-usual congestion day"),
        (_bucket("ordinary_high"), "ordinary_high", "a busier-than-usual congestion day"),
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
        (_bucket("split"), "split",
         "afternoon splits: {positive_label} prices higher than {negative_label}"),
        (_bucket("concentrated"), "concentrated", "weight is concentrated in {zone}"),
        (_bucket("tilted"), "tilted", "weight leans toward {zone}"),
        (_bucket("distributed"), "distributed", "weight is spread across zones"),
        (lambda _slot: True, "unknown", "the available geography is incomplete"),
    ),
    "exceptions": (
        (lambda slot: slot.get("bucket") == "several" and slot.get("tier_0_count") == 1,
         "several", "{count} constraints not included in the model stand apart; one is newly active"),
        (lambda slot: slot.get("bucket") == "several" and slot.get("tier_0_count", 0) > 0,
         "several", "{count} constraints not included in the model stand apart; "
         "{tier_0_count} are newly active"),
        (_bucket("several"), "several", "{count} constraints not included in the model stand apart"),
        (lambda slot: slot.get("bucket") == "one_or_two" and slot.get("count") == 1,
         "one", "one constraint not included in the model stands apart"),
        (_bucket("one_or_two"), "one_or_two", "{count} constraints not included in the model stand apart"),
        (_bucket("unavailable"), "unavailable", "exceptions await DAM settlement"),
        (lambda _slot: True, "none", "no constraints not included in the model stand apart"),
    ),
}


def phrase_for(slot_name: str, slot: Slot) -> tuple[str, str]:
    """Return ``(bucket, text)`` from an ordered, exhaustive ladder."""
    for predicate, bucket, template in LADDERS[slot_name]:
        if predicate(slot):
            return bucket, template.format(**slot)
    raise AssertionError(f"{slot_name} phrase ladder is not exhaustive")


def _high_congestion_detail(slot: Slot) -> str | None:
    """Expose only a material intraday disagreement with the whole-day rung."""
    high = slot.get("high_congestion_hours")
    if not high or high.get("bucket") not in MAGNITUDE_RUNGS:
        return None
    # The whole-day verdict keeps fine-rung distance. This prose guard instead
    # compares coarse bands so adding ordinary_low/high does not make a formerly
    # one-band ordinary→elevated difference suddenly editorial-worthy.
    coarse = {"ordinary_low": "ordinary", "ordinary_high": "ordinary"}
    coarse_rungs = ("quiet", "ordinary", "elevated", "near_top", "record_high")
    delta = (coarse_rungs.index(coarse.get(high["bucket"], high["bucket"]))
             - coarse_rungs.index(coarse.get(slot["bucket"], slot["bucket"])))
    if abs(delta) < 2:
        return None
    labels = {
        "quiet": "quiet",
        "ordinary_low": "quieter than usual",
        "ordinary": "ordinary",
        "ordinary_high": "busier than usual",
        "elevated": "elevated",
        "near_top": "near-record",
        "record_high": "at a record high",
    }
    connector = "though" if delta > 0 else "but"
    return f"; {connector} high-congestion hours were {labels[high['bucket']]}"


def _sentence_start(text: str) -> str:
    """Capitalize a template when it begins a rendered sentence."""
    return text[:1].upper() + text[1:]


def render(slots: dict[str, Slot]) -> dict[str, list[dict[str, str]]]:
    """Render tooltip-ready text segments; callers never parse a flat string."""
    magnitude = phrase_for("magnitude", slots["magnitude"])[1]
    regime = phrase_for("regime", slots["regime"])[1]
    where = phrase_for("where", slots["where"])[1]
    exceptions = phrase_for("exceptions", slots["exceptions"])[1]
    detail = _high_congestion_detail(slots["magnitude"])
    headline = [
        {"text": f"{_sentence_start(magnitude)}. ", "ref": "magnitude"},
        {"text": _sentence_start(where), "ref": "where"},
    ]
    if detail:
        headline.append({"text": detail, "ref": "magnitude"})
    headline.append({"text": ".", "ref": "where"})
    return {
        "headline": headline,
        "lede": [
            {"text": regime, "ref": "regime"},
            {"text": "; ", "ref": "exceptions"},
            {"text": exceptions, "ref": "exceptions"},
            {"text": ".", "ref": "magnitude"},
        ],
    }
