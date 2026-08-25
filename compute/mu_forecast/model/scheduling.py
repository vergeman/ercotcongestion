"""Calendar-safe fold and chunk scheduling for the μ walk."""
from __future__ import annotations

import pandas as pd


def refit_boundaries(panel: pd.DataFrame, train_days: int, refit_days: int,
                     score_from: pd.Timestamp | None = None,
                     anchor: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    """The weekly refit grid, phase-locked to `sf/eval`.

    `score_from` is a real `sf/eval` week start, pinning the phase exactly;
    `anchor` remains for standalone use. Generate in the origin's own timezone
    with a `DateOffset`, then convert: converting first locks the grid to UTC's
    wall clock, while a `Timedelta` is DST-oblivious. Both errors yield tidy,
    silently hour-shifted weekly rows after a DST transition.
    """
    days = pd.DatetimeIndex(
        panel.index.get_level_values("interval_ts").normalize().unique()).sort_values()
    step = pd.DateOffset(days=refit_days)
    if score_from is not None:
        origin = pd.Timestamp(score_from)
        floor = origin - pd.Timedelta(days=train_days)
        if floor < pd.Timestamp(days[0]).tz_convert(origin.tz):
            raise ValueError(
                f"score_from={origin.date()} needs {train_days}d of history back to "
                f"{floor.date()}, but the panel starts {days[0].date()}. The first "
                "week would train on a short window and score anyway — refusing.")
        end = pd.Timestamp(days[-1]).tz_convert(origin.tz)
        return pd.date_range(origin, end, freq=step, inclusive="left").tz_convert(days.tz)

    origin = pd.Timestamp(anchor) if anchor is not None else pd.Timestamp(days[0])
    start = origin + pd.DateOffset(days=train_days)
    end = pd.Timestamp(days[-1]).tz_convert(origin.tz)
    return pd.date_range(start, end, freq=step, inclusive="left").tz_convert(days.tz)


def score_chunks(score_from: pd.Timestamp, end: pd.Timestamp, refit_days: int,
                 chunk_weeks: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Partition the fixed scored grid into exclusive-end chunk windows.

    `DateOffset`, not `Timedelta`, preserves CT midnight across DST transitions.
    """
    if chunk_weeks < 1:
        raise ValueError("chunk_weeks must be positive")
    end = pd.Timestamp(end).tz_convert(score_from.tz)
    step = pd.DateOffset(days=refit_days)
    starts = pd.date_range(score_from, end, freq=step, inclusive="left")
    return [(block[0], block[-1] + step)
            for block in (starts[i:i + chunk_weeks]
                          for i in range(0, len(starts), chunk_weeks)) if len(block)]
