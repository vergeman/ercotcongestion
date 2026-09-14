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
from api.config import FRONTEND_ORIGIN
from api.db import lifespan
from api.routes import conditions, ercot_range, forecast, map, matrix, scoreboard, topology
from api.routes.analysis import brief, catalog, hero, insights

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

app = FastAPI(
    title='Power Grid Snapshot API',
    description='Serves settlement-point topology and realized ERCOT congestion/SPP ranges.',
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
#   /topology  /ercot_range  /forecast_range
#   /conditions_range
#   /map/summary  /map/constraints  /map/exposures  /map/reach
#   /scoreboard/summary
app.include_router(topology.router,    tags=['topology'])
app.include_router(ercot_range.router, tags=['ercot_range'])
app.include_router(forecast.router,    tags=['forecast'])
app.include_router(conditions.router,  tags=['conditions'])
app.include_router(map.router,         tags=['map'])
app.include_router(matrix.router,      tags=['matrix'])
app.include_router(scoreboard.router,  tags=['scoreboard'])
app.include_router(catalog.router,     tags=['analysis'])
app.include_router(insights.router,    tags=['analysis'])
app.include_router(hero.router,        tags=['analysis'])
app.include_router(brief.router,       tags=['analysis'])


@app.get('/healthz', tags=['meta'])
def healthz() -> dict[str, str]:
    return {'status': 'ok'}
