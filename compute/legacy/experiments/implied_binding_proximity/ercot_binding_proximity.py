"""ERCOT-side binding proximity from DAM binding constraints (NP4-191-CD)
and DAM SP congestion components. No constraint locations required.

Method:
  DAM identity: congestion[h, sp] = -sum_c SF[c, sp] * mu[h, c]
  Ridge-regress the SP congestion panel on the shadow-price panel over a
  rolling window to recover implied shift factors, then per hour:
      bp_ercot[sp, h] = max over constraints binding in h of |SF_implied[c, sp]|
  (DAM reports only binding rows -> loading fraction = 1.)

Usage:
    python ercot_binding_proximity.py \
        --constraints-glob 'data/np4191/*.csv' \
        --congestion-glob  'data/dam_congestion/*.csv' \
        --window-days 60 --out bp_ercot.csv
"""

from __future__ import annotations

import argparse
import glob

import numpy as np
import pandas as pd

MIN_BINDING_HOURS = 10   # drop constraints binding fewer hours in the window
RIDGE_LAMBDA = 1e-2


# ---------------------------------------------------------------- ingest

def load_constraints(paths: list[str]) -> pd.DataFrame:
    """Stack daily NP4-191-CD files -> long df [ts, key, mu]."""
    frames = []
    for p in paths:
        df = pd.read_csv(p)
        df["key"] = (
            df["ConstraintName"].astype(str).str.strip()
            + "|"
            + df["ContingencyName"].astype(str).str.strip()
        )
        he = df["HourEnding"].str[:2].astype(int)          # '01:00'..'24:00'
        df["ts"] = pd.to_datetime(df["DeliveryDate"]) + pd.to_timedelta(he - 1, unit="h")
        frames.append(df[["ts", "key", "ShadowPrice"]])
    return pd.concat(frames, ignore_index=True).rename(columns={"ShadowPrice": "mu"})


def load_congestion(paths: list[str]) -> pd.DataFrame:
    """Stack daily congestion files -> long df [ts, settlement_point, congestion]."""
    frames = []
    for p in paths:
        df = pd.read_csv(p, parse_dates=["interval_ct"])
        df["ts"] = df["interval_ct"] - pd.Timedelta(hours=1)  # hour-ending -> hour-start
        frames.append(df[["ts", "settlement_point", "congestion"]])
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- core

def build_panels(con: pd.DataFrame, spc: pd.DataFrame):
    """Aligned wide panels: M (hours x constraints), C (hours x SPs)."""
    M = con.pivot_table(index="ts", columns="key", values="mu", aggfunc="sum")
    C = spc.pivot_table(index="ts", columns="settlement_point", values="congestion")
    idx = M.index.union(C.index).sort_values()
    return M.reindex(idx).fillna(0.0), C.reindex(idx)  # zero-mu hours are real


def implied_shift_factors(
    M: pd.DataFrame,
    C: pd.DataFrame,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
) -> pd.DataFrame:
    """Ridge solve for SF (constraints x SPs) on the given window."""
    keep = (M > 0).sum() >= min_hours
    Mk = M.loc[:, keep[keep].index]
    rows = C.notna().any(axis=1)
    X = Mk.loc[rows].values
    Y = C.loc[rows].fillna(0.0).values
    K = X.shape[1]
    if K == 0:
        return pd.DataFrame(columns=C.columns)
    beta = np.linalg.solve(X.T @ X + lam * np.eye(K), X.T @ Y)
    return pd.DataFrame(-beta, index=Mk.columns, columns=C.columns)


def binding_proximity(M: pd.DataFrame, SF: pd.DataFrame) -> pd.DataFrame:
    """bp[ts, sp] = max over constraints binding at ts of |SF[c, sp]|."""
    common = M.columns.intersection(SF.index)
    A = (M[common] > 0).values                # hours x K activity mask
    S = np.abs(SF.loc[common].values)         # K x n_sp
    bp = np.zeros((A.shape[0], S.shape[1]))
    for i in range(A.shape[0]):
        if A[i].any():
            bp[i] = S[A[i]].max(axis=0)
    return pd.DataFrame(bp, index=M.index, columns=SF.columns)


def rolling_bp(
    con: pd.DataFrame,
    spc: pd.DataFrame,
    window_days: int = 60,
) -> pd.DataFrame:
    """For each day, fit SF on the trailing window (incl. that day), score its hours."""
    M_all, C_all = build_panels(con, spc)
    days = pd.Series(M_all.index.normalize().unique()).sort_values()
    out = []
    for day in days:
        lo = day - pd.Timedelta(days=window_days)
        win = (M_all.index >= lo) & (M_all.index < day + pd.Timedelta(days=1))
        SF = implied_shift_factors(M_all.loc[win], C_all.loc[win])
        if SF.empty:
            continue
        today = M_all.index.normalize() == day
        out.append(binding_proximity(M_all.loc[today], SF))
    return pd.concat(out) if out else pd.DataFrame()


# ---------------------------------------------------------------- cli

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--constraints-glob", required=True)
    ap.add_argument("--congestion-glob", required=True)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--out", default="bp_ercot.csv")
    args = ap.parse_args()

    con = load_constraints(sorted(glob.glob(args.constraints_glob)))
    spc = load_congestion(sorted(glob.glob(args.congestion_glob)))
    bp = rolling_bp(con, spc, window_days=args.window_days)

    long = bp.stack().rename("bp_ercot").reset_index()
    long.columns = ["ts", "settlement_point", "bp_ercot"]
    long.to_csv(args.out, index=False)
    print(f"wrote {args.out}: {long.shape[0]} rows, "
          f"{long.settlement_point.nunique()} SPs, {long.ts.nunique()} hours")


if __name__ == "__main__":
    main()
