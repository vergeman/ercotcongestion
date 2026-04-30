FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pypsa \
    pandas \
    dotenv \
    psycopg \
    psycopg[binary] \
    psycopg[pool] \
    pytest \
    httpx \
    openpyxl \
    numpy \
    matpowercaseframes \
    scipy \
    fastapi \
    uvicorn

RUN groupadd -g 1000 shifty && useradd -m -u 1000 -g 1000 shifty
USER shifty
CMD ["python"]
