"""Postgres connection pool, owned by the FastAPI app lifespan."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from config import PG_DSN

# Module-level pool; opened in lifespan, closed on shutdown.
pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: open pool on startup, close on shutdown."""
    global pool
    pool = ConnectionPool(
        conninfo=PG_DSN,
        min_size=1,
        max_size=8,
        kwargs={'autocommit': True},
    )
    pool.wait()
    try:
        yield
    finally:
        pool.close()
        pool = None


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("DB pool not initialized — is the app running under lifespan?")
    return pool
