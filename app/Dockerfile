FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pypsa \
    pandas \
    numpy \
    matpowercaseframes \
    scipy \
    fastapi \
    uvicorn

CMD ["python"]
