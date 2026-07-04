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
from config import FRONTEND_ORIGIN
from db import lifespan
import state, topology, validation, ptdf, ercot_state

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

app = FastAPI(
    title='Power Grid Snapshot API',
    description='Serves topology, state, and state_range endpoints.',
    version='0.1.0',
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGIN,
    allow_credentials=False,
    allow_methods=['GET'],
    allow_headers=['*'],
)

# Routers mounted at root. URLs:
#   /topology  /state  /state_range  /validation  /ptdf
app.include_router(state.router,       tags=['state'])
app.include_router(topology.router,    tags=['topology'])
app.include_router(validation.router,  tags=['validation'])
app.include_router(ptdf.router,        tags=['ptdf'])
app.include_router(ercot_state.router, tags=['ercot_state'])


@app.get('/healthz', tags=['meta'])
def healthz() -> dict[str, str]:
    return {'status': 'ok'}
