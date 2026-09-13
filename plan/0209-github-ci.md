# 0209 - github-ci

Type: chore
Branch: chore/0209-github-ci

## Goal

* Extract the inline Dockerfile dep list into a root `requirements.txt` consumed by both the `Dockerfile` and CI (single source of truth).
* Add `.github/workflows/ci.yml` running two jobs on PRs into `master` and pushes to `master`.
* Python job: `pip install -r requirements.txt`, run `pytest` across `api`, `ercot_ingest`, `compute` (unit only).
* Web job: `npm ci` + `eslint` + `tsc -b && vite build` in `web/`.

## Context

* No `.github/` exists; there is no CI today.
* Web is built + deployed by Cloudflare's own GitHub integration; API/compute ships via `./build.sh` → ECR + `ops/deploy` (both stay manual — **no CD in scope**).
* Python deps live inline in the root `Dockerfile` (no `requirements.txt`); target runtime is Python 3.13, `PYTHONPATH=.:compute` (repo root makes `api`/`compute`/`shared` importable).
* Tests mock the DB; integration tests are gated behind `RUN_INTEGRATION=1` and must stay skipped in CI.
* Web needs Node ≥ 20 (Vite 8 / TS 6); repo's `web/Dockerfile` uses `node:22`.

## Approach

### Commit 1 — extract `requirements.txt` (complete: `a69973b`)

* New file `requirements.txt` at repo root with the exact deps from `Dockerfile` lines 24–40, one per line, preserving pins:
  `requests`, `fastapi`, `uvicorn[standard]`, `pytest`, `pypsa==1.2.2`, `pandas`, `numpy`, `scipy`, `scikit-learn`, `pyarrow`, `folium`, `psycopg[binary,pool]`, `matpowercaseframes`, `openpyxl`, `python-dotenv`, `httpx`.
* Edit `Dockerfile`: replace the inline `RUN pip install --no-cache-dir \ ...` block (lines 24–40) with a `COPY requirements.txt /tmp/requirements.txt` + `RUN pip install --no-cache-dir -r /tmp/requirements.txt`. Place the COPY before the install so layer caching keys on the manifest only.
* Verify image still builds: `docker build -t api-compute:ci-check .` (or note as manual check if Docker unavailable).

### Commit 2 — CI workflow (complete: `2285c04`)

* Work in: `.github/workflows/ci.yml` (new) and `README.md` (CI badge).
* Triggers: `pull_request: { branches: [master] }` and `push: { branches: [master] }`.
* **Job `python-tests`**:
  * `runs-on: ubuntu-latest`, `actions/setup-python@v5` with `python-version: '3.13'` and `cache: pip` + `cache-dependency-path: requirements.txt` (native pip cache now that a manifest exists).
  * `pip install -r requirements.txt`.
  * Run `PYTHONPATH=.:compute pytest api ercot_ingest compute` with `RUN_INTEGRATION` unset (integration auto-skips). Set inert ERCOT/proxy values needed by ingest imports; no secrets or external calls are used.
* **Job `web`**:
  * `runs-on: ubuntu-latest`, `actions/setup-node@v4` with `node-version: '22'`, `cache: npm`, `cache-dependency-path: web/package-lock.json`.
  * `working-directory: web` → `npm ci`, `npm run lint`, `npm run build`.
* Jobs run in parallel (no `needs`).
* Do NOT touch: `build.sh`, `ops/**`, `web/**` source, or add any deploy/ECR/kubectl step. (`Dockerfile` is edited only for the requirements.txt swap above.)

## Acceptance

* [x] `requirements.txt` exists at root; `Dockerfile` installs from it; deps match the previous inline list exactly (no additions/removals).
* [x] `docker build .` succeeds using the new manifest.
* [x] `.github/workflows/ci.yml` exists; YAML parses clean.
* [x] Opening a PR into `master` triggers both jobs; direct push to `master` triggers both.
* [x] Python job installs deps (cached on rerun) and `pytest` collects + passes with integration tests skipped.
* [x] Web job runs `eslint` and produces a successful `vite build`.
* [x] No workflow performs any deploy, ECR push, or `kubectl` action.
