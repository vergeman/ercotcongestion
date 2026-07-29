"""F6 — after-action: push realized DAM μ through the SAME S, then diff.

Once DAM shadow prices and SPPs land, the forecast is graded against reality on
three axes (docs/daily_brief_engine.md):

* **ranking scorecard** — the predicted top-K constraints vs the realized top-K
  (recall, exact hits, the worst severity miss and false alarm), which isolates
  *constraint-selection* error;
* **spread decomposition** — ``forecast spread → +Δ(μ̂→μ_DAM) → spatial residual
  → actual DAM SPP spread`` for a headline pair, which splits *severity* error
  (Δμ) from *reconstruction* error (the spatial residual);
* **hub triple** — each hub's forecast / reconstruction / realized congestion,
  and whether realized fell inside the forecast P10–P90 band.

Everything runs through the artifact's own SF (never a refit), so the
reconstruction isolates μ error from the recovered spatial operator. All
functions are pure; the job supplies the realized panels.
"""
from __future__ import annotations

import pandas as pd

from compute.analysis.brief import TOP_K_CONSTRAINTS


def spread_decomposition(cong_fc: pd.Series, cong_recon: pd.Series,
                         realized: pd.Series | None, a: str, b: str) -> dict:
    """Split the ``a − b`` spread into severity (Δμ) and reconstruction residual.

    ``forecast_spread + delta_mu + spatial_residual = actual_spread`` exactly,
    where ``recon_spread = forecast_spread + delta_mu`` is realized μ through the
    same S. When either endpoint has no realized DAM SPP, ``actual_spread`` and
    ``spatial_residual`` are ``None`` (recon is still available).
    """
    fc = float(cong_fc[a] - cong_fc[b])
    recon = float(cong_recon[a] - cong_recon[b])
    have_real = (realized is not None and a in realized.index and b in realized.index
                 and pd.notna(realized[a]) and pd.notna(realized[b]))
    actual = float(realized[a] - realized[b]) if have_real else None
    return {
        "a": str(a),
        "b": str(b),
        "forecast_spread": fc,
        "delta_mu": recon - fc,
        "recon_spread": recon,
        "spatial_residual": (actual - recon) if actual is not None else None,
        "actual_spread": actual,
    }


def _order(score: pd.Series) -> list:
    return sorted(score.index, key=lambda k: (-float(score[k]), str(k)))


def scorecard(pred_score: pd.Series, real_score: pd.Series,
              top_k: int = TOP_K_CONSTRAINTS) -> dict:
    """Predicted-vs-realized constraint ranking (same reach, two μ vectors).

    Reports recall within top-K, exact positional hits, and the two error
    exemplars: the realized-important constraint the forecast most underranked
    (severity miss) and the predicted-important one reality most demoted (false
    alarm). Scores are ``|μ| × reach`` for the hour, or ``|μ|-mass × reach`` for
    the day — the caller decides the currency.
    """
    pred_order, real_order = _order(pred_score), _order(real_score)
    pred_rank = {k: i for i, k in enumerate(pred_order, start=1)}
    real_rank = {k: i for i, k in enumerate(real_order, start=1)}
    top_k = min(top_k, len(pred_order))       # never index past the constraint set
    pred_top, real_top = pred_order[:top_k], real_order[:top_k]

    predicted = [{
        "constraint_key": str(k),
        "predicted_rank": pred_rank[k],
        "realized_rank": real_rank[k],
    } for k in pred_top]

    miss = max(real_top, key=lambda k: pred_rank[k])       # underranked by forecast
    alarm = max(pred_top, key=lambda k: real_rank[k])      # demoted by reality
    return {
        "top_k": top_k,
        "recall_at_k": len(set(pred_top) & set(real_top)) / top_k,
        "exact_hits": sum(1 for i in range(top_k) if pred_order[i] == real_order[i]),
        "predicted": predicted,
        "biggest_severity_miss": {"constraint_key": str(miss),
                                  "predicted_rank": pred_rank[miss],
                                  "realized_rank": real_rank[miss]},
        "biggest_false_alarm": {"constraint_key": str(alarm),
                                "predicted_rank": pred_rank[alarm],
                                "realized_rank": real_rank[alarm]},
    }


def hub_triples(cong_fc: pd.Series, cong_recon: pd.Series,
                realized: pd.Series | None, p10: pd.Series | None,
                p90: pd.Series | None, hubs: list[str]) -> list[dict]:
    """Per hub: forecast / reconstruction / realized congestion + P10–P90 check."""
    def _at(s, h):
        return float(s[h]) if (s is not None and h in s.index and pd.notna(s[h])) else None

    triples = []
    for h in hubs:
        realized_v = _at(realized, h)
        lo, hi = _at(p10, h), _at(p90, h)
        in_band = (lo <= realized_v <= hi) if None not in (realized_v, lo, hi) else None
        triples.append({
            "settlement_point": str(h),
            "forecast": _at(cong_fc, h),
            "reconstruction": _at(cong_recon, h),
            "realized": realized_v,
            "p10": lo,
            "p90": hi,
            "in_band": in_band,
        })
    return triples


def dam_match_coverage(mu_fc: pd.Series, mu_dam_row: pd.Series) -> float:
    """Fraction of forecast ``|μ̂|`` mass on constraints the DAM feed carries."""
    total = float(mu_fc.abs().sum())
    if not total:
        return 0.0
    matched = mu_fc.index.intersection(mu_dam_row.index)
    return float(mu_fc.loc[matched].abs().sum()) / total


def hour_after_action(*, reach: pd.Series, mu_fc: pd.Series, mu_dam_row: pd.Series,
                      cong_fc: pd.Series, cong_recon: pd.Series,
                      realized: pd.Series | None, p10: pd.Series | None,
                      p90: pd.Series | None, hubs: list[str], dipole: dict,
                      best_pair: dict | None = None,
                      top_k: int = TOP_K_CONSTRAINTS) -> dict:
    """Assemble one hour's after-action from realized DAM panels.

    ``mu_dam_row`` is the hour's realized shadow prices over the DAM vocabulary
    (before alignment); ``cong_recon`` is that μ pushed through the artifact SF.
    The F5a ``dipole`` and (when present) the F5b ``best_pair`` each get their
    severity-vs-reconstruction decomposition — the best pair's endpoints are
    DAM-covered by construction, so its actual SPP spread is always available.
    """
    mu_dam = mu_dam_row.reindex(reach.index).fillna(0.0)
    card = scorecard(mu_fc.abs() * reach, mu_dam.abs() * reach, top_k)
    # Attach the two μ values to each predicted row for the waterfall view.
    for entry in card["predicted"]:
        k = entry["constraint_key"]
        entry["mu_forecast"] = float(mu_fc[k]) if k in mu_fc.index else None
        entry["mu_dam"] = float(mu_dam[k]) if k in mu_dam.index else None

    def _decompose(pair, hi_key, lo_key):
        if not pair or not pair.get(hi_key) or not pair.get(lo_key):
            return None
        return spread_decomposition(cong_fc, cong_recon, realized,
                                    pair[hi_key]["settlement_point"],
                                    pair[lo_key]["settlement_point"])

    return {
        "dam_match_coverage": dam_match_coverage(mu_fc, mu_dam_row),
        "scorecard": card,
        "hub_dipole_decomposition": _decompose(dipole, "max", "min"),
        "best_pair_decomposition": _decompose(best_pair, "sink", "source"),
        "hub_triple": hub_triples(cong_fc, cong_recon, realized, p10, p90, hubs),
    }
