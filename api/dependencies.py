"""Shared FastAPI dependencies for public read routes."""
from __future__ import annotations


def server_selected_run() -> None:
    """Leave model-run selection to the route's server-side resolver."""
    return None
