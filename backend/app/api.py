from __future__ import annotations

import csv
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .core.policies import PolicyConfig
from .core.simulator import SimulationConfig, run_experiment
from .core.workload import Workload, generate_workload
from .db import ExperimentRun, create_run, get_session, init_db, list_runs
from .kubernetes_dry_run import KubernetesInspectionError, inspect_deployment_read_only
from .schemas import ExperimentRequest, RunConfig, SyntheticRequest

@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="HybridScale Research API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

DATA_DIR = Path(os.getenv("HYBRIDSCALE_DATA_DIR", "data"))
RESULTS_DIR = DATA_DIR / "results"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_CSV_ROWS = 100_000


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hybridscale-api"}


@app.post("/api/experiments/synthetic")
def run_synthetic(payload: SyntheticRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        workload = generate_workload(payload.scenario, payload.length, payload.seed)
        return _execute(workload, payload.config, payload.scenario, payload.seed, session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/experiments")
def run_uploaded_data(payload: ExperimentRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        workload = Workload(payload.timestamps, payload.demand, payload.signal_name, payload.unit)
        if len(workload.demand) != len(payload.timestamps):
            raise ValueError("timestamps and demand must have the same length")
        return _execute(workload, payload.config, payload.scenario, payload.seed, session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/experiments/upload-csv")
async def upload_csv(
    file: Annotated[UploadFile, File()],
    config_json: Annotated[str, Form()] = "{}",
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=415, detail="Upload a .csv file")
    config = _parse_config(config_json)
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="CSV exceeds the 20 MiB upload limit")
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "timestamp" not in reader.fieldnames or "demand" not in reader.fieldnames:
            raise ValueError("CSV must have timestamp and demand columns")
        timestamps: list[int] = []
        demand: list[float] = []
        for row_number, row in enumerate(reader, start=2):
            if len(timestamps) >= MAX_CSV_ROWS:
                raise ValueError(f"CSV exceeds {MAX_CSV_ROWS} rows")
            timestamps.append(int(float(row["timestamp"])))
            demand.append(float(row["demand"]))
        workload = Workload(timestamps, demand)
        return _execute(workload, config, "csv_upload", None, session)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded") from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@app.get("/api/experiments")
def get_experiments(limit: int = 50, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_run_summary(run) for run in list_runs(session, max(1, min(limit, 200)))]


@app.get("/api/experiments/{run_id}")
def get_experiment(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(ExperimentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Experiment not found")
    result_file = Path(run.result_path)
    if not result_file.is_file():
        raise HTTPException(status_code=500, detail="Experiment result file is missing")
    return json.loads(result_file.read_text(encoding="utf-8"))


@app.get("/api/experiments/{run_id}/export")
def export_experiment(run_id: str, session: Session = Depends(get_session)) -> StreamingResponse:
    run = session.get(ExperimentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Experiment not found")
    result_file = Path(run.result_path)
    if not result_file.is_file():
        raise HTTPException(status_code=500, detail="Experiment result file is missing")
    data = json.loads(result_file.read_text(encoding="utf-8"))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["policy", "step", "timestamp", "demand", "forecast", "forecast_target_step", "forecast_error_mae", "forecast_nmae", "ready_replicas", "desired_replicas", "pending_replicas", "activated_this_step", "capacity", "capacity_violation", "unmet_demand", "excess_capacity", "utilization", "policy_target", "requested_delta", "reasons"])
    writer.writeheader()
    for policy in data["policies"]:
        for row in policy["steps"]:
            writer.writerow({**row, "policy": policy["policy"], "reasons": ";".join(row["reasons"])})
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="hybridscale-{run_id}.csv"'})


@app.post("/api/kubernetes/recommendation")
def kubernetes_recommendation(
    namespace: str = Form(...),
    deployment: str = Form(...),
    min_replicas: int = Form(1, ge=0),
    max_replicas: int = Form(20, ge=1),
    target_utilization: float = Form(0.70, gt=0, le=1),
) -> dict[str, Any]:
    try:
        return inspect_deployment_read_only(namespace, deployment, min_replicas, max_replicas, target_utilization)
    except KubernetesInspectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _parse_config(config_json: str) -> RunConfig:
    from pydantic import ValidationError
    try:
        return RunConfig.model_validate_json(config_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False)) from exc


def _execute(workload: Workload, config: RunConfig, scenario: str, seed: int | None, session: Session) -> dict[str, Any]:
    policy_config = PolicyConfig(**config.policy.model_dump())
    sim_config = SimulationConfig(
        interval_seconds=config.interval_seconds,
        initial_replicas=config.initial_replicas,
        readiness_delay_steps=config.readiness_delay_steps,
        forecast_horizon_steps=config.forecast_horizon_steps,
        forecast_bias=config.forecast_bias,
        forecast_noise_std=config.forecast_noise_std,
        forecast_lag_steps=config.forecast_lag_steps,
        forecast_degradation_start_step=config.forecast_degradation_start_step,
        forecast_degradation_bias=config.forecast_degradation_bias,
        forecast_seed=config.forecast_seed,
        policy=policy_config,
    )
    result = run_experiment(workload, sim_config)
    run_id = str(uuid4())
    result["run_id"] = run_id
    result["workload"].update({"scenario": scenario, "seed": seed, "steps": len(workload.demand)})
    path = RESULTS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(result, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    summary = {p["policy"]: p["metrics"] for p in result["policies"]}
    create_run(session, run_id=run_id, workload_metadata=result["workload"], config=result["config"], summary=summary, result_path=str(path))
    return {"run_id": run_id, "result_type": "simulation", "workload": result["workload"], "summary": summary, "detail_url": f"/api/experiments/{run_id}", "export_url": f"/api/experiments/{run_id}/export"}


def _run_summary(run: ExperimentRun) -> dict[str, Any]:
    return {"id": run.id, "created_at": run.created_at.isoformat(), "status": run.status, "result_type": run.result_type, "workload": run.workload_metadata, "config": run.config, "summary": run.summary}
