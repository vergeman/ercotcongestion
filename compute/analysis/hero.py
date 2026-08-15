"""Pure classification for the daily-brief hero.

The database reader deliberately lives elsewhere: these functions accept the
small trailing-window summaries it produces and return JSON-safe slot values.
Keeping the thresholds here makes both the vocabulary and the grading contract
testable without a database.
"""
from __future__ import annotations

from statistics import median
from typing import Any


MAGNITUDE_RUNGS = (
    "quiet", "ordinary_low", "ordinary", "ordinary_high", "elevated", "near_top", "record_high",
)


def _rank(value: float, prior: list[float]) -> tuple[int, int]:
    """Return one-based descending rank after appending today's value.

    Ties get the conservative (last tied) position.  This avoids claiming a
    record merely because an equal prior day happened to sort after today.
    """
    return 1 + sum(other >= value for other in prior), len(prior) + 1


def _magnitude_bucket(rank: int, ratio: float | None) -> str:
    if rank == 1:
        return "record_high"
    if rank <= 3:
        return "near_top"
    if ratio is not None and ratio >= 1.25:
        return "elevated"
    if ratio is not None and ratio <= 0.5:
        return "quiet"
    if ratio is not None and ratio < 0.75:
        return "ordinary_low"
    if ratio is not None and ratio >= 1.10:
        return "ordinary_high"
    return "ordinary"


def classify_magnitude(summary: dict[str, Any]) -> dict[str, Any]:
    """Classify one artifact-key (or all-DAM-key) daily congestion total.

    ``prior`` must contain only days before the delivery day.  The value is
    ranked after being appended, so a trailing-30-day read reports ``of 31``.
    """
    value = float(summary["value"])
    prior = [float(v) for v in summary["prior"]]
    med = float(median(prior)) if prior else None
    ratio = value / med if med not in (None, 0.0) else None
    rank, n = _rank(value, prior)
    result = {
        "value": value,
        "rank": rank,
        "n": n,
        "med": med,
        "ratio": ratio,
        "basis": summary["basis"],
        "n_keys": int(summary["n_keys"]),
        "prior_last": prior[-1] if prior else None,
    }
    result["bucket"] = _magnitude_bucket(rank, ratio)
    if "hours_ct" in summary:
        result["hours_ct"] = list(summary["hours_ct"])
    if "all_keys" in summary:
        result["all_keys"] = classify_magnitude(summary["all_keys"])
    if "high_congestion_hours" in summary:
        result["high_congestion_hours"] = classify_magnitude(summary["high_congestion_hours"])
    return result


def classify_regime(summary: dict[str, Any]) -> dict[str, Any]:
    """Classify a condition-series percentile; conditions have no DAM actual."""
    pct = float(summary["pct"])
    series = str(summary["series"])
    if pct >= 100:
        bucket = "load_record_high" if series == "load.system" else "record_high"
    elif pct >= 95:
        bucket = "near_record_high"
    elif pct <= 5:
        bucket = "near_record_low"
    else:
        bucket = "ordinary"
    return {**summary, "pct": pct, "bucket": bucket, "reconcilable": False}


def classify_where(summary: dict[str, Any]) -> dict[str, Any]:
    """Name the largest μ-weighted zone share without inventing place names."""
    shares = {str(k): float(v) for k, v in summary["zone_shares"].items()}
    if not shares:
        return {**summary, "zone": None, "share": None, "bucket": "unknown"}
    zone, share = sorted(shares.items(), key=lambda item: (-item[1], item[0]))[0]
    split = summary.get("benchmark_split")
    if split:
        return {**summary, "zone_shares": shares, "zone": zone, "share": share,
                **split, "bucket": "split"}
    # The 365-day audit separates a true spread (<45%) from the broad middle
    # (45–55%): a 49% leader should not read as qualitatively unlike a 51%
    # leader.  Reserve “concentrated” for a clear 55% majority.
    bucket = "concentrated" if share >= 0.55 else "tilted" if share >= 0.45 else "distributed"
    return {**summary, "zone_shares": shares, "zone": zone, "share": share,
            "bucket": bucket}


def classify_exceptions(summary: dict[str, Any]) -> dict[str, Any]:
    """Classify settled DAM constraints absent from the artifact vocabulary."""
    if summary.get("available") is False:
        return {**summary, "available": False, "bucket": "unavailable"}
    tier_0 = list(summary.get("tier_0", []))
    tier_1 = list(summary.get("tier_1", []))
    count = len({item["constraint_key"] for item in tier_0 + tier_1})
    bucket = "none" if count == 0 else "several" if count >= 3 else "one_or_two"
    return {**summary, "tier_0": tier_0, "tier_1": tier_1,
            "tier_0_count": len(tier_0), "tier_1_count": len(tier_1),
            "count": count, "bucket": bucket}


def classify_slots(window: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Classify the four hero slots from one query-layer result."""
    return {
        "magnitude": classify_magnitude(window["magnitude"]),
        "regime": classify_regime(window["regime"]),
        "where": classify_where(window["where"]),
        "exceptions": classify_exceptions(window["exceptions"]),
    }


def magnitude_verdict(forecast: dict[str, Any], settled: dict[str, Any]) -> dict[str, Any]:
    """Grade magnitude by distance on its existing bucket ladder.

    No second set of arbitrary grading thresholds is introduced: a settled day
    two rungs above the morning call is simply ``under_called`` by two rungs.
    """
    delta = MAGNITUDE_RUNGS.index(settled["bucket"]) - MAGNITUDE_RUNGS.index(forecast["bucket"])
    if delta > 0:
        bucket = "under_called"
    elif delta < 0:
        bucket = "over_called"
    else:
        bucket = "held"
    return {"bucket": bucket, "rungs": abs(delta)}
