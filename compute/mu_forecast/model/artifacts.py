"""Prediction artifact serialization for the μ walk."""
from __future__ import annotations

import os
import zipfile

import numpy as np
import pandas as pd


def save_preds(path: str, preds: pd.DataFrame) -> None:
    """Write the prediction frame as a compressed, timezone-safe NPZ."""
    df = preds.reset_index()
    codes, vocab = pd.factorize(df["key"], sort=True)

    def epoch_us(s: pd.Series) -> np.ndarray:
        return (pd.DatetimeIndex(s).tz_convert("UTC").tz_localize(None)
                .to_numpy("datetime64[us]").astype("int64"))

    np.savez_compressed(
        path,
        interval_ts=epoch_us(df["interval_ts"]),
        week=epoch_us(df["week"]),
        key_code=codes.astype("int32"),
        key_vocab=np.asarray(vocab, dtype=object).astype("U"),
        p_bind=df["p_bind"].to_numpy("float32"),
        mu_gbm=df["mu_gbm"].to_numpy("float32"),
        y_bind=df["y_bind"].to_numpy("int8"),
        y_mu=df["y_mu"].to_numpy("float32"),
    )


_PRED_ARRAY_DTYPES = {
    "interval_ts": np.dtype("int64"),
    "week": np.dtype("int64"),
    "key_code": np.dtype("int32"),
    "p_bind": np.dtype("float32"),
    "mu_gbm": np.dtype("float32"),
    "y_bind": np.dtype("int8"),
    "y_mu": np.dtype("float32"),
}


def combine_pred_chunks(paths: list[str], output: str) -> int:
    """Stream chunk NPZs into the standard complete prediction artifact."""
    if not paths:
        raise ValueError("cannot combine zero prediction chunks")

    vocab_parts: list[np.ndarray] = []
    n_rows = 0
    for path in paths:
        with np.load(path, allow_pickle=False) as z:
            vocab_parts.append(z["key_vocab"])
            n_rows += len(z["interval_ts"])
    vocab = np.unique(np.concatenate(vocab_parts))
    tmp = f"{output}.tmp"
    os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)

    def write_member(zf: zipfile.ZipFile, name: str, dtype: np.dtype, chunks) -> None:
        header = {"descr": dtype.str, "fortran_order": False, "shape": (n_rows,)}
        with zf.open(f"{name}.npy", "w", force_zip64=True) as fh:
            np.lib.format.write_array_header_2_0(fh, header)
            for values in chunks:
                fh.write(np.ascontiguousarray(values, dtype=dtype).tobytes())

    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as zf:
            with zf.open("key_vocab.npy", "w", force_zip64=True) as fh:
                np.save(fh, vocab, allow_pickle=False)
            for name, dtype in _PRED_ARRAY_DTYPES.items():
                def arrays(name=name):
                    for path in paths:
                        with np.load(path, allow_pickle=False) as z:
                            if name == "key_code":
                                keys = z["key_vocab"][z["key_code"]]
                                yield np.searchsorted(vocab, keys).astype("int32")
                            else:
                                yield z[name]
                write_member(zf, name, dtype, arrays())
        os.replace(tmp, output)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return n_rows


def load_preds(path: str) -> pd.DataFrame:
    """Load either artifact generation, returning active prediction columns.

    Earlier artifacts include an inactive conditional-climatology array. It is
    intentionally not exposed so callers have one stable, active contract.
    """
    with np.load(path, allow_pickle=False) as z:
        vocab = z["key_vocab"]
        df = pd.DataFrame({
            "interval_ts": pd.to_datetime(z["interval_ts"], unit="us", utc=True),
            "key": vocab[z["key_code"]],
            "week": pd.to_datetime(z["week"], unit="us", utc=True),
            "p_bind": z["p_bind"], "mu_gbm": z["mu_gbm"],
            "y_bind": z["y_bind"], "y_mu": z["y_mu"],
        })
    return df.set_index(["interval_ts", "key"])
