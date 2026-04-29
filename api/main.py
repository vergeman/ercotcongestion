"""FastAPI application entry point.

Run locally:
    docker compose run --rm --service-ports api \\
        uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Production:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import FRONTEND_ORIGINS
from db import lifespan
import state

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

app = FastAPI(
    title='Power Grid Snapshot API',
    description='Serves topology, state, and state_range endpoints.',
    version='0.1.0',
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=['GET'],
    allow_headers=['*'],
)

app.include_router(state.router,    prefix='/api', tags=['state'])

@app.get('/healthz', tags=['meta'])
def healthz() -> dict[str, str]:
    return {'status': 'ok'}
