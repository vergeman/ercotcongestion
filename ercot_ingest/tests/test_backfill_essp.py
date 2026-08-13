"""Vintage selection for NP4-158-SG (study vs final within a posting day)."""
import pandas as pd

from backfill_essp import ENDPOINT_FINAL, ENDPOINT_STUDY, _select_vintages


def test_select_vintages_keeps_latest_study_and_final():
    docs = pd.DataFrame({
        "docId": [1, 2, 3, 4],
        "posted": pd.to_datetime([
            "2026-07-27T05:55:00",
            "2026-07-27T05:56:00",  # study correction
            "2026-07-27T13:03:00",
            "2026-07-27T13:05:00",  # final correction
        ]),
    })

    vintages = _select_vintages(docs)

    assert [(endpoint, row.docId) for endpoint, row in vintages] == [
        (ENDPOINT_STUDY, 2), (ENDPOINT_FINAL, 4),
    ]


def test_select_vintages_study_only_before_dam_clears():
    docs = pd.DataFrame({
        "docId": [1],
        "posted": pd.to_datetime(["2026-07-27T05:55:00"]),
    })

    vintages = _select_vintages(docs)

    assert [(endpoint, row.docId) for endpoint, row in vintages] == [
        (ENDPOINT_STUDY, 1),
    ]
