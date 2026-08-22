"""Pure, leakage-safe feature engineering for the μ panel.

These transformations do not read the database.  Binding history is strictly
backward-looking; net-load buckets fit only on their supplied training window;
and audit data is derived from the vintages actually selected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from compute.mu.availability import ERCOT_TZ, dam_close, delivery_day_of, history_cutoff


def calendar_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Build free calendar features, including cyclic hour encodings."""
    local = pd.DatetimeIndex(idx).tz_convert(ERCOT_TZ)
    out = pd.DataFrame(index=idx)
    out["hour"] = local.hour
    out["dow"] = local.dayofweek
    out["month"] = local.month
    out["is_weekend"] = (local.dayofweek >= 5).astype(int)
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    return out


def net_load_regime(panel: pd.DataFrame, fit_index: pd.DatetimeIndex,
                    n_buckets: int = 5) -> pd.Series:
    """Bucket net load using quantile edges fitted only on ``fit_index``."""
    train = panel.loc[panel.index.isin(fit_index), "net_load"].dropna()
    if train.empty:
        return pd.Series(-1, index=panel.index, name="net_load_regime")
    edges = np.unique(np.quantile(train, np.linspace(0, 1, n_buckets + 1)[1:-1]))
    labels = np.digitize(panel["net_load"].to_numpy(), edges)
    out = pd.Series(labels, index=panel.index, name="net_load_regime")
    return out.where(panel["net_load"].notna(), -1)


def candidate_keys(hist: pd.DataFrame, policy: str = "active_28d") -> pd.DataFrame:
    """Choose every historical key or only keys binding in the trailing 28 days."""
    if policy == "all":
        return hist
    if policy == "active_28d":
        return hist[hist["binds_28d"] > 0]
    raise ValueError(f"unknown candidate policy: {policy!r}")


def downcast_join(frame: pd.DataFrame) -> pd.DataFrame:
    """Downcast merge inputs before the wide panel can become float64-wide."""
    float64 = frame.select_dtypes("float64").columns
    if len(float64):
        frame[float64] = frame[float64].astype("float32")
    return frame


def attach_refit_features(panel: pd.DataFrame, days: pd.DatetimeIndex,
                          values: pd.DataFrame) -> None:
    """Attach weekly per-key refit values without copying the wide panel."""
    if values.empty or not len(days):
        return
    if not values.index.is_unique:
        raise ValueError("refit feature values must have one row per key")
    positions = np.flatnonzero(panel["delivery_day"].isin(days).to_numpy())
    if not len(positions):
        return
    aligned = values.reindex(panel.iloc[positions]["key"])
    for col in aligned.columns:
        if col not in panel:
            panel[col] = np.full(len(panel), np.nan, dtype=np.float32)
        panel.iloc[positions, panel.columns.get_loc(col)] = aligned[col].to_numpy(
            dtype=np.float32, na_value=np.nan)


def audit_leakage(panel: pd.DataFrame) -> pd.DataFrame:
    """Report whether selected source vintages were published after DAM close."""
    rows = []
    for col in [col for col in panel.columns if col.startswith("vintage_")]:
        used = pd.to_datetime(panel[col]).dropna()
        if used.empty:
            continue
        published = pd.DatetimeIndex(used)
        if published.tz is None:
            published = published.tz_localize("UTC")
        closes = pd.DatetimeIndex([dam_close(day) for day in delivery_day_of(used.index)])
        slack_h = (closes - published) / pd.Timedelta(hours=1)
        rows.append({"source": col.removeprefix("vintage_"), "n_rows": len(used),
                     "min_slack_h": float(np.min(slack_h)),
                     "median_slack_h": float(np.median(slack_h)),
                     "n_leaks": int((slack_h < 0).sum())})
    return pd.DataFrame(rows)


def binding_history(M: pd.DataFrame, days: pd.DatetimeIndex,
                    bind_deadband: float, history_windows: tuple[int, ...],
                    lag_windows: tuple[int, ...]) -> pd.DataFrame:
    """Build per-day, per-key history using only intervals before ``history_cutoff``.

    Lagged magnitudes average all observed hours, including slack zeroes; DST day
    lengths come from the source index rather than a hard-coded 24.
    """
    binds = M.fillna(0.0).abs() > bind_deadband
    mu = M.fillna(0.0).abs().where(binds, 0.0)
    day_idx = delivery_day_of(M.index)
    daily_binds = binds.groupby(day_idx).sum()
    daily_mu = mu.groupby(day_idx).sum()
    daily_peak = mu.groupby(day_idx).max()
    daily_hours = pd.Series(1, index=M.index).groupby(day_idx).sum()
    frames = []
    for day in days:
        cutoff_day = history_cutoff(day).tz_convert(ERCOT_TZ).tz_localize(None).normalize()
        past_days = daily_binds.index[daily_binds.index < cutoff_day]
        if not len(past_days):
            continue
        binds_before = daily_binds.loc[past_days]
        mu_before = daily_mu.loc[past_days]
        peak_before = daily_peak.loc[past_days]
        hours_before = daily_hours.loc[past_days]
        row = {}
        for window in history_windows:
            recent = binds_before.iloc[-window:] if window <= len(binds_before) else binds_before
            row[f"binds_{window}d"] = recent.sum()
        row["bind_rate_life"] = binds_before.sum() / max(len(binds_before) * 24, 1)
        row["mean_mu_28d"] = (mu_before.iloc[-28:].sum()
                              / binds_before.iloc[-28:].sum().replace(0, np.nan))
        for window in lag_windows:
            row[f"lag_mu_{window}d"] = (mu_before.iloc[-window:].sum()
                                          / max(int(hours_before.iloc[-window:].sum()), 1))
            row[f"lag_max_mu_{window}d"] = peak_before.iloc[-window:].max()
        ever = binds_before.loc[:, binds_before.sum() > 0]
        last = pd.Series(len(binds_before), index=binds_before.columns, dtype=float)
        if not ever.empty:
            positions = ever.apply(lambda column: np.flatnonzero(column.to_numpy() > 0)[-1])
            last.loc[ever.columns] = len(binds_before) - 1 - positions
        row["days_since_bind"] = last
        frame = pd.DataFrame(row)
        frame["delivery_day"] = day
        frame.index.name = "key"
        frames.append(frame.reset_index())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).set_index(["delivery_day", "key"]).fillna(0.0)
