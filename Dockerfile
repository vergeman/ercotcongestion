# Single image used by api, ingest cron, and snapshot-writer jobs.
# Replaces the old api/Dockerfile and compute/Dockerfile.
#
# Build from repo root:
#   docker build -t api-compute:<tag> .
#
# Layout inside the image:
#   /api             FastAPI app
#   /compute         snapshot writer + supporting modules
#   /ercot_ingest    live_updater + ErcotClient
#   /opt/shared      shared.settings package (PYTHONPATH=/opt → import shared)
#   /data/processed  preprocessing artifacts (CSVs + .nc network)
#   /api/static      writable cache directory (e.g. topology.json)

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Combined dep set (api + compute + ingest).
RUN pip install --no-cache-dir \
        fastapi \
        uvicorn[standard] \
        pypsa \
        pandas \
        numpy \
        scipy \
        psycopg[binary,pool] \
        matpowercaseframes \
        openpyxl \
        python-dotenv \
        httpx

# Create the unprivileged user before COPY so we can chown in one shot.
RUN groupadd -g 1000 shifty && useradd -m -u 1000 -g 1000 shifty

# Code and shared package.
COPY --chown=shifty:shifty shared/        /opt/shared/
COPY --chown=shifty:shifty api/           /api/
COPY --chown=shifty:shifty compute/       /compute/
COPY --chown=shifty:shifty ercot_ingest/  /ercot_ingest/

# Preprocessing artifacts (CSVs + netCDF).
# Phase 2: still baked in. Move to S3 init container or PVC if these start
# changing more frequently than the code.
COPY --chown=shifty:shifty data/processed /data/processed/

# API writes its topology cache here on first request.
RUN mkdir -p /api/static && chown shifty:shifty /api/static

# PYTHONPATH:
#   /api      → api modules (config, db, state, topology, ...)
#   /compute  → compute modules (snapshot, write_snapshots, ...)
#   /opt      → shared package
ENV PYTHONPATH=/api:/compute:/opt \
    MALLOC_ARENA_MAX=2 \
    PYTHONUNBUFFERED=1

USER shifty
WORKDIR /api

EXPOSE 8000

# Default command runs the API. Cron jobs override with their own commands.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
