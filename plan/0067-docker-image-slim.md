# 0067 - docker-image-slim

Type: chore
Branch: chore/0067-docker-image-slim

## Goal

* Cut the `api-compute` image from ~1.54 GB to ~800 MB–1 GB with no runtime behavior change.
* Keep a single Dockerfile that serves `api`, `compute`, `updater`, and `preprocess` (per docker-compose).
* Preserve the `PYTHONPATH` layout and `shifty` user contract already in the image.

## Context

* `docker history` on the current image shows the fat lives in two layers: `pip install` (~1.12 GB) and `apt install gcc/g++/libpq5` (~259 MB). `gcc`/`g++` are only needed to build wheels — not at runtime — because psycopg uses `[binary]` and pypsa/scipy/numpy/sklearn all ship manylinux wheels.
* `.dockerignore` is missing entries; `COPY compute/` pulls in `compute/runs/` (~79 MB on disk), `compute/experiments/`, `__pycache__/`, and `*.md` files. The compute layer lands at 44.4 MB but is mostly artifacts.
* Grep confirms `folium` is used only in `compute/clustering/browse_zones.py` (diagnostic), `matpowercaseframes` + `openpyxl` only in `preprocess/build_network.py`, and `pytest` only in test files — none are needed at runtime for `api`/`compute`/`updater`.
* Constraint: the same image runs `api` (uvicorn), `compute` (python shell), `updater` (`python /ercot_ingest/live_updater.py`), and the `preprocess` profile — build_network runs inside the image, so `matpowercaseframes` + `openpyxl` must remain unless preprocess gets a separate image (out of scope here).

## Approach

* Work in: repo root — `Dockerfile`, `.dockerignore`, `build.sh`.
* Do NOT touch: `docker-compose.yml` service definitions (image tag interface unchanged), `ops/deploy/**` manifests, application code, or `web/Dockerfile`.
* Each step below is one commit. Verify image size with `docker images | grep api-compute` and smoke-test with `docker compose up api` + a request to `/` after each.

### Commit 1 — Tighten `.dockerignore`

* Add to `.dockerignore`:
  ```
  **/__pycache__/
  **/*.pyc
  **/*.pyo
  compute/runs/
  compute/experiments/
  compute/sample_specs/
  compute/**/*.md
  compute/**/tests/
  compute/test_*.py
  compute/verify_*.py
  api/tests/
  .git/
  .claude/
  .image-tag
  fragility_map.png
  summary.md
  *.md
  !README.md
  ```
* Expected: `COPY compute/` layer drops from 44.4 MB → ~1 MB.

### Commit 2 — Drop `pytest` from prod deps

* Remove `pytest` from the `pip install` line in `Dockerfile`.
* If any dev/test workflow relies on it, install via `pip install pytest` inside the container on demand or add a `requirements-dev.txt` (do not wire into the image).
* Expected: minor (~5 MB) but simplifies the dep set before the next step.

### Commit 3 — Multi-stage build, drop toolchain from runtime

* Rewrite `Dockerfile` as two stages:
  * **builder** (`FROM python:3.13-slim AS builder`): installs `gcc g++ libpq-dev`, runs the same `pip install --no-cache-dir ...` into `/install` via `pip install --prefix=/install` (or a venv at `/opt/venv`).
  * **runtime** (`FROM python:3.13-slim`): installs only `libpq5`, copies `/install` (or `/opt/venv`) from builder, then does the `groupadd`/`useradd`, `COPY`s, `mkdir /api/static`, `ENV`, `USER shifty`, `WORKDIR /api`, `EXPOSE 8000`, `CMD`.
* Keep `ENV PYTHONPATH=/api:/compute:/:/opt MALLOC_ARENA_MAX=2 PYTHONUNBUFFERED=1` in runtime stage.
* Expected: ~200 MB dropped (gcc/g++ and headers no longer in final image).

### Commit 4 — Strip bytecode + test dirs from site-packages

* In the builder stage, after `pip install`, add:
  ```
  RUN find /install -depth \
        \( -type d -a \( -name __pycache__ -o -name tests -o -name test \) \
         -o -type f -a \( -name '*.pyc' -o -name '*.pyo' \) \) \
        -exec rm -rf {} +
  ```
* Set `ENV PYTHONDONTWRITEBYTECODE=1` in the runtime stage to keep it clean at runtime.
* Expected: ~100–200 MB depending on how much scipy/sklearn bundles.

### Commit 5 — Verify + document

* Update the header comment in `Dockerfile` to reflect the multi-stage layout.
* Run through the acceptance checklist below on a clean build (`docker build --no-cache -t api-compute:slim .`).
* Do NOT touch `build.sh` unless `--target` is needed (it isn't — final stage is the default).

## Acceptance

* [ ] `docker build -t api-compute:slim .` succeeds; `docker images` shows the tag at ≤ 1.0 GB.
* [ ] `docker history api-compute:slim` shows no `gcc`/`g++` layer in the final stage.
* [ ] `docker compose up api` starts; `GET http://localhost:8000/` returns a successful response.
* [ ] `docker compose run --rm compute python -c "import pypsa, pandas, scipy, sklearn, psycopg; print('ok')"` prints `ok`.
* [ ] `docker compose run --rm updater python -c "from ercot_ingest.live_updater import *"` imports without error (or the module's own smoke check passes).
* [ ] `docker compose --profile tools run --rm preprocess python -c "import matpowercaseframes, openpyxl; print('ok')"` prints `ok`.
* [ ] `docker run --rm api-compute:slim find / -name '*.pyc' 2>/dev/null | wc -l` is 0.
* [ ] `docker run --rm api-compute:slim ls /compute/runs 2>&1 | grep -q 'No such'` — runs artifacts are not baked in.
* [ ] No changes to `docker-compose.yml`, `ops/deploy/**`, or application code.
