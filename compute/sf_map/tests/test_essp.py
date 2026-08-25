import pandas as pd

from compute.evaluation.essp import agreement


def test_agreement_scores_exact_signature_precision_and_recall():
    # a/b and c/d are identical SF signatures. ERCOT agrees on a/b but separates
    # c/d, while its c/e group is not recovered. Both ratios are therefore 1/2.
    SF = pd.DataFrame({
        "a": [1.0, 2.0], "b": [1.0, 2.0],
        "c": [3.0, 4.0], "d": [3.0, 4.0], "e": [5.0, 6.0],
    }, index=["k1", "k2"])
    essp = pd.DataFrame([
        ("2026-07-28T00:00Z", "a", 1), ("2026-07-28T00:00Z", "b", 1),
        ("2026-07-28T00:00Z", "c", 2), ("2026-07-28T00:00Z", "e", 2),
        ("2026-07-28T00:00Z", "d", 3),
    ], columns=["interval_ts", "settlement_point", "group_index"])

    assert agreement(SF, essp) == {"essp_precision": 0.5, "essp_recall": 0.5}


def test_agreement_returns_null_without_informative_groups():
    SF = pd.DataFrame({"a": [1.0], "b": [2.0]}, index=["k"])
    essp = pd.DataFrame([("2026-07-28T00:00Z", "a", 1)],
                        columns=["interval_ts", "settlement_point", "group_index"])
    assert agreement(SF, essp) == {"essp_precision": None, "essp_recall": None}
