"""On-disk codecs and read-time helpers for SF projection artifacts.

encode/decode the nodal panel and the per-day SF+μ blob, and explain a node's
price. Imported by the forecast/backfill jobs, ``compute.forecast_store``, and
the API read path.

These classes get imported into daily_forecast.py.

"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd

#
# Nodal Panel
#
@dataclass
class NodalPanel:
    """One window's ragged settlement-point forecast grid."""
    ts: np.ndarray
    settlement_points: np.ndarray
    point: np.ndarray
    sf_r2: np.ndarray | None


def _epoch_us(idx) -> np.ndarray:
    """Return UTC microseconds, matching the prediction artifact timestamp codec."""
    di = pd.DatetimeIndex(idx)
    if di.tz is not None:
        di = di.tz_convert("UTC").tz_localize(None)
    return di.to_numpy("datetime64[us]").astype("int64")

#
# Nodal Accuumlator
3

class _NodalAccumulator:
    """Stream ragged panels to the flat vocab-coded nodal artifact.

    "Vocab" = the list of unique labels (settlement points, constraint keys).
    Each row stores a small integer *code* into that list instead of the
    string, so millions of rows over ~1,120 points cost a 4-byte code plus one
    shared table rather than a repeated string. Decode is ``vocab[code]``.

    """
    def __init__(self) -> None:
        self._sp_code: dict[str, int] = {}
        self._buf: dict[str, list[np.ndarray]] = {
            k: [] for k in ("ts", "sp_code", "point", "week")}

    def add(self, panel: NodalPanel, week: pd.Timestamp) -> None:
        H, N = len(panel.ts), len(panel.settlement_points)
        code = np.fromiter(
            (self._sp_code.setdefault(str(sp), len(self._sp_code))
             for sp in panel.settlement_points), dtype=np.int32, count=N)
        b = self._buf
        b["ts"].append(np.repeat(_epoch_us(panel.ts), N))
        b["sp_code"].append(np.tile(code, H))
        b["point"].append(panel.point.ravel())
        b["week"].append(np.full(H * N, int(_epoch_us(pd.DatetimeIndex([week]))[0]),
                                 dtype=np.int64))

    def save(self, path: str) -> None:
        cols = {k: (np.concatenate(v) if v else np.empty(0, np.int64))
                for k, v in self._buf.items()}
        save_nodal(path, cols, np.array(list(self._sp_code), dtype=object).astype("U"))


def save_nodal(path: str, cols: dict[str, np.ndarray], sp_vocab: np.ndarray) -> None:
    """Write a flat nodal panel as compressed NPZ."""
    np.savez_compressed(
        path, ts=cols["ts"].astype("int64"), sp_code=cols["sp_code"].astype("int32"),
        sp_vocab=np.asarray(sp_vocab, dtype=object).astype("U"),
        point=cols["point"].astype("float32"),
        week=cols["week"].astype("int64"))


def load_nodal(path: str) -> pd.DataFrame:
    """Decode a flat nodal NPZ into a tidy UTC frame."""
    z = np.load(path, allow_pickle=False)
    return pd.DataFrame({
        "ts": pd.to_datetime(z["ts"], unit="us", utc=True),
        "settlement_point": z["sp_vocab"][z["sp_code"]],
        "point": z["point"],
        "week": pd.to_datetime(z["week"], unit="us", utc=True)})


#
# SfMu Artifact
#
@dataclass
class SfMuArtifact:
    """A day's SF matrix and expected μ values on the same constraint vocabulary."""
    SF: pd.DataFrame
    E_mu: pd.DataFrame


def build_sf_mu_artifact(SF: pd.DataFrame, E_mu: pd.DataFrame) -> bytes:
    """Serialize the day's SF and expected μ matrices to an NPZ blob."""
    E = E_mu.reindex(columns=SF.index)
    buf = io.BytesIO()
    np.savez_compressed(
        buf, key_vocab=np.asarray(SF.index, dtype=object).astype("U"),
        sp_vocab=np.asarray(SF.columns, dtype=object).astype("U"),
        sf=SF.to_numpy(np.float32), ts=_epoch_us(E.index), e_mu=E.to_numpy(np.float32))
    return buf.getvalue()


def save_sf_mu(path: str, SF: pd.DataFrame, E_mu: pd.DataFrame) -> None:
    """Write the SF-and-μ artifact bytes to disk."""
    with open(path, "wb") as fh:
        fh.write(build_sf_mu_artifact(SF, E_mu))


def load_sf_mu(src) -> SfMuArtifact:
    """Decode an SF-and-μ artifact from a path or bytes."""
    z = np.load(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src,
                allow_pickle=False)
    keys = z["key_vocab"]
    return SfMuArtifact(
        SF=pd.DataFrame(z["sf"], index=keys, columns=z["sp_vocab"]),
        E_mu=pd.DataFrame(z["e_mu"], index=pd.to_datetime(z["ts"], unit="us", utc=True),
                          columns=keys))


DRIVERS_K = 10
DRIVERS_MAX_DAYS = 14


def node_drivers(art: SfMuArtifact, sp: str, ts, k: int = DRIVERS_K) -> pd.DataFrame:
    contrib = -(art.E_mu.loc[pd.Timestamp(ts)] * art.SF[sp])
    contrib = contrib[contrib != 0.0]
    top = contrib.reindex(contrib.abs().sort_values(ascending=False).index).head(k)
    return pd.DataFrame({"ts": pd.Timestamp(ts), "settlement_point": sp,
                         "constraint": top.index.to_numpy(), "contrib": top.to_numpy(dtype=float),
                         "abs_contrib": top.abs().to_numpy(dtype=float),
                         "exposure": float(art.SF[sp].abs().max())})


def node_contributions(art: SfMuArtifact, sp: str, mu: pd.Series) -> pd.Series:
    if sp not in art.SF.columns:
        raise KeyError(sp)
    return -(art.SF[sp] * mu.reindex(art.SF.index).fillna(0.0))


def materialize_drivers(art: SfMuArtifact, k: int = DRIVERS_K, sps=None) -> pd.DataFrame:
    sps = list(art.SF.columns) if sps is None else list(sps)
    frames = [node_drivers(art, sp, ts, k) for ts in art.E_mu.index for sp in sps]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts", "settlement_point", "constraint", "contrib", "abs_contrib", "exposure"])


def parse_curated_days(spec: str | None) -> list[pd.Timestamp]:
    if spec is None or not spec.strip():
        raise ValueError("--drivers needs an explicit comma-separated day list, "
                         "e.g. 2025-06-01,2025-07-15 (curated debug only)")
    if ":" in spec:
        raise ValueError("--drivers takes explicit days, not a span 'a:b' — driver "
                         "rows are curated debug output, never a full-history run")
    days = [pd.Timestamp(t.strip()) for t in spec.split(",") if t.strip()]
    if not days:
        raise ValueError("--drivers day list is empty")
    if len(days) > DRIVERS_MAX_DAYS:
        raise ValueError(f"--drivers is for curated days (<= {DRIVERS_MAX_DAYS}), got "
                         f"{len(days)} — that is not a curated set (§2.4, §5a)")
    return days
