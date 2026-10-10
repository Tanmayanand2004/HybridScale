# HybridScale

HybridScale is a research prototype for comparing reactive, predictive, and hybrid autoscaling policies under controlled workloads, forecast errors, and replica readiness delays. It reports simulator capacity proxies; it does not measure application latency, service-level objectives, or cloud spend.

## Components

- `backend/`: Python, FastAPI, simulator, API, persistence, and read-only Kubernetes recommendation adapter.
- `frontend/`: React, TypeScript, and Vite research workbench.
- `experiments/`: seeded simulator studies, analysis, integrity audits, and default configuration.
- `docker-compose.yml`: PostgreSQL, API, and frontend containers.

Experiment outputs, databases, trace datasets, paper drafts, and project research documents are not included in this code repository.

## Run locally

### Backend

```bash
python -m venv .venv
# Activate the environment, then:
pip install -r backend/requirements.txt
uvicorn backend.app.api:app --reload
```

The API defaults to `http://localhost:8000` and uses SQLite locally. Set `DATABASE_URL` to use PostgreSQL.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open the Vite URL shown in the terminal. The frontend expects the API at `http://localhost:8000` by default.

### Docker Compose

Copy `.env.example` to `.env`, set a strong local `POSTGRES_PASSWORD`, then run:

```bash
docker compose up --build
```

The frontend is exposed on port `5173` and the API on port `8000`, bound to localhost.

## API

- `GET /api/health`
- `POST /api/experiments/synthetic`
- `POST /api/experiments` (JSON time series)
- `POST /api/experiments/upload-csv` (`timestamp,demand`; maximum 20 MiB and 100,000 rows)
- `GET /api/experiments` and `GET /api/experiments/{id}`
- `GET /api/experiments/{id}/export` (step-level CSV)
- `POST /api/kubernetes/recommendation` (read-only, explicitly gated)

## Safety and scope

The Kubernetes adapter is disabled by default and produces read-only recommendations. The simulator models demand and ready replica capacity; it does not include an application service curve, request queue, latency, SLO, or pricing model. Treat its outcomes as synthetic capacity proxies, not production performance claims.

## Development checks

```bash
python -m pytest backend/tests
cd frontend && npm run build
```

Docker Compose requires Docker Desktop or another running Docker daemon.

