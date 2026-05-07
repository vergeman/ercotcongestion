FROM python:3.13-slim

# System deps for scipy/numpy wheels and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Python deps. Match versions to compute/Dockerfile to keep behavior consistent.
# PyPSA is needed at runtime by api/services/ptdf_service.py and topology_builder.py.
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
        python-dotenv

# Layout:
#   /opt/shared      shared.settings
#   /api             api package (mounted as working dir)
#   /data/processed  baked-in CSVs and netCDF (Phase 1; later: PVC or S3 init)
WORKDIR /api

RUN groupadd -g 1000 shifty && useradd -m -u 1000 -g 1000 shifty

COPY --chown=shifty:shifty shared/        /opt/shared/
COPY --chown=shifty:shifty api/           /api/
COPY                       data/processed /data/processed/

RUN mkdir -p /api/static && chown shifty:shifty /api/static

ENV PYTHONPATH=/api:/opt \
    PYTHONUNBUFFERED=1

USER shifty

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
