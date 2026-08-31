"""Map workspace bootstrap composition."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from api.schemas.common import BootstrapSectionStatus
from api.schemas.map import MapSummaryResponse
from api.services.bootstrap import availability_status, soft_fail
from api.services.scoreboard_headline import build_headline
from api.services.topology_builder import get_or_build_topology


def build(
    *, overview: Callable[[], object], meta: Callable[[], object]
) -> MapSummaryResponse:
    """Compose Map's load-time quartet without coupling its independent sources.

    Topology runs on the request thread while overview, meta, and headline use
    the three pool workers; interaction endpoints remain separate.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        overview_future = pool.submit(soft_fail, overview)
        meta_future = pool.submit(soft_fail, meta)
        headline_future = pool.submit(soft_fail, lambda: build_headline(None))
        topology = get_or_build_topology()
        overview_result = overview_future.result()
        meta_result = meta_future.result()
        headline_result = headline_future.result()

    return MapSummaryResponse(
        topology=topology,
        overview=overview_result,
        meta=meta_result,
        headline=headline_result,
        availability={
            "topology": BootstrapSectionStatus(available=True),
            "overview": availability_status(overview_result, BootstrapSectionStatus),
            "meta": availability_status(meta_result, BootstrapSectionStatus),
            "headline": availability_status(headline_result, BootstrapSectionStatus),
        },
    )
