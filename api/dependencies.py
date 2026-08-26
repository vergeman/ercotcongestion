"""Shared FastAPI dependencies for public read routes."""
from __future__ import annotations

from fastapi import Query


def server_selected_run(run_id: str | None = Query(None)) -> str | None:
    """Accept an optional explicit run, otherwise defer selection to the route."""
    return run_id
