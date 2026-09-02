"""The hero phrase book.

Templates are intentionally separate from the slot classifiers.  Bucket names
are the stable API contract; changing the voice changes this file, not numeric
thresholds or frontend parsing.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from compute.analysis.hero_classifier import MAGNITUDE_RUNGS


Slot = dict[str, Any]
Ladder = tuple[tuple[Callable[[Slot], bool], str, str], ...]


def _bucket(name: str) -> Callable[[Slot], bool]:
    return lambda slot: slot.get("bucket") == name


def _num(slot: Slot, key: str) -> float | None:
    value = slot.get(key)
    return float(value) if isinstance(value, (int, float)) else None


# Driver-clause thresholds. Wind/solar are ranked over the trailing year on the
# peak CT window; a settled forecast miss is a percent of the DAM-close call.
WIND_LOW_PCT = 15.0
WIND_HIGH_PCT = 85.0
SOLAR_HIGH_PCT = 85.0
LOAD_MISS_MIN_PCT = 3.0


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
         "afternoon splits: {positive_label} prices above {negative_label} "
         "by ${spread:.0f}/MWh"),
        (_bucket("concentrated"), "concentrated", "weight is concentrated in {zone}"),
        (_bucket("tilted"), "tilted", "weight leans toward {zone}"),
        (_bucket("distributed"), "distributed", "weight is spread across zones"),
        (lambda _slot: True, "unknown", "the available geography is incomplete"),
    ),
    # The lede's first clause: the single most salient grid driver behind the
    # day, or nothing.  Renewable supply into the peak leads (it explains a
    # congestion day the boxed load level cannot); a settled forecast miss and
    # strong midday solar follow.  Load level/rank/region are already in the
    # stat boxes, so the lede deliberately never restates them.
    "driver": (
        (lambda s: (_num(s, "wind_pct") or 100.0) <= WIND_LOW_PCT,
         "wind_light", "wind running light into the afternoon peak"),
        (lambda s: (_num(s, "wind_pct") or 0.0) >= WIND_HIGH_PCT,
         "wind_strong", "wind running strong into the afternoon peak"),
        (lambda s: (_num(s, "load_miss_pct") or 0.0) >= LOAD_MISS_MIN_PCT,
         "load_over", "load landed {load_miss_pct:.0f}% above the DAM forecast"),
        (lambda s: (_num(s, "load_miss_pct") or 0.0) <= -LOAD_MISS_MIN_PCT,
         "load_under", "load landed {load_miss_abs:.0f}% below the DAM forecast"),
        (lambda s: (_num(s, "solar_pct") or 0.0) >= SOLAR_HIGH_PCT,
         "solar_strong", "solar running strong into the afternoon peak"),
        (lambda _slot: True, "none", ""),
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


def _coverage_clause(slots: dict[str, Slot]) -> tuple[str, str]:
    """The always-present lede tail: how much of the day the model spoke to.

    Before DAM settlement there is no system total to divide by, so the clause
    reports the pending state instead of a number.  When settled it reframes the
    old constraint-count caveat as a coverage share of realized congestion.
    """
    exceptions = slots.get("exceptions", {})
    if exceptions.get("available") is False or exceptions.get("bucket") == "unavailable":
        return "exceptions", "awaiting DAM settlement"
    magnitude = slots["magnitude"]
    total = _num(magnitude.get("all_keys") or {}, "value")
    modeled = _num(magnitude, "value")
    if not total or total <= 0 or modeled is None:
        return "magnitude", "system congestion was negligible"
    share = max(0.0, min(1.0, modeled / total))
    return "magnitude", f"modeled constraints captured {share * 100:.0f}% of system congestion"


def _lede_segments(slots: dict[str, Slot]) -> list[dict[str, str]]:
    """Optional driver clause, then the always-present coverage clause."""
    driver = phrase_for("driver", slots["regime"])[1]
    coverage_ref, coverage = _coverage_clause(slots)
    if driver:
        return [
            {"text": _sentence_start(driver), "ref": "regime"},
            {"text": "; ", "ref": coverage_ref},
            {"text": coverage, "ref": coverage_ref},
            {"text": ".", "ref": coverage_ref},
        ]
    return [
        {"text": _sentence_start(coverage), "ref": coverage_ref},
        {"text": ".", "ref": coverage_ref},
    ]


def render(slots: dict[str, Slot]) -> dict[str, list[dict[str, str]]]:
    """Render tooltip-ready text segments; callers never parse a flat string."""
    magnitude = phrase_for("magnitude", slots["magnitude"])[1]
    where = phrase_for("where", slots["where"])[1]
    detail = _high_congestion_detail(slots["magnitude"])
    headline = [
        {"text": f"{_sentence_start(magnitude)}. ", "ref": "magnitude"},
        {"text": _sentence_start(where), "ref": "where"},
    ]
    if detail:
        headline.append({"text": detail, "ref": "magnitude"})
    headline.append({"text": ".", "ref": "where"})
    return {"headline": headline, "lede": _lede_segments(slots)}
