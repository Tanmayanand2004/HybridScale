"""Run the preregistered HybridScale synthetic pilot or confirmatory matrix.

Run from the project root, for example:
    python experiments/run_study.py --mode pilot
    python experiments/run_study.py --mode confirmatory

Each output directory is new and immutable by convention. Raw per-step policy
trajectories are stored as gzip NDJSON; per-run metrics and a manifest are
written alongside them. No trace data or network access is needed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.policies import PolicyConfig  # noqa: E402
from backend.app.core.simulator import SimulationConfig, run_experiment  # noqa: E402
from backend.app.core.workload import SCENARIOS, generate_workload  # noqa: E402

SCENARIOS_ORDERED = ("stable", "gradual", "burst", "periodic", "volatile", "shift")
CONDITIONS: dict[str, dict[str, float | int | None]] = {
    "clean": {"forecast_bias": 0.0, "forecast_noise_std": 0.0, "forecast_lag_steps": 0,
              "forecast_degradation_start_step": None, "forecast_degradation_bias": 0.0},
    "underpredict_25pct": {"forecast_bias": -0.25, "forecast_noise_std": 0.0, "forecast_lag_steps": 0,
                           "forecast_degradation_start_step": None, "forecast_degradation_bias": 0.0},
    "overpredict_25pct": {"forecast_bias": 0.25, "forecast_noise_std": 0.0, "forecast_lag_steps": 0,
                          "forecast_degradation_start_step": None, "forecast_degradation_bias": 0.0},
    "noise_0_5": {"forecast_bias": 0.0, "forecast_noise_std": 0.5, "forecast_lag_steps": 0,
                  "forecast_degradation_start_step": None, "forecast_degradation_bias": 0.0},
    "stale_1_step": {"forecast_bias": 0.0, "forecast_noise_std": 0.0, "forecast_lag_steps": 1,
                     "forecast_degradation_start_step": None, "forecast_degradation_bias": 0.0},
    "degraded_after_step_120": {"forecast_bias": 0.0, "forecast_noise_std": 0.0, "forecast_lag_steps": 0,
                                "forecast_degradation_start_step": 120, "forecast_degradation_bias": -0.50},
}
DELAYS = (0, 2, 4)
SEEDS = tuple(range(1000, 1030))
LENGTH = 240
INTERVAL_SECONDS = 300


def _new_output(name: str | None, mode: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = name or f"v1_{mode}_{stamp}"
    if not safe_name or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in safe_name):
        raise ValueError("output name may contain only letters, digits, underscores, and hyphens")
    root = (PROJECT_ROOT / "experiments" / "results").resolve()
    out = (root / safe_name).resolve()
    if root not in out.parents:
        raise ValueError("output must stay inside experiments/results")
    out.mkdir(parents=True, exist_ok=False)
    return out


def _run_configuration(scenario: str, condition_name: str, delay: int, seed: int) -> dict[str, Any]:
    condition_index = list(CONDITIONS).index(condition_name)
    forecast_seed = seed * 1009 + condition_index
    config = SimulationConfig(
        interval_seconds=INTERVAL_SECONDS,
        initial_replicas=2,
        readiness_delay_steps=delay,
        forecast_horizon_steps=2,
        forecast_seed=forecast_seed,
        policy=PolicyConfig(
            target_utilization=0.70,
            min_replicas=1,
            max_replicas=20,
            max_scale_up_step=4,
            max_scale_down_step=2,
            cooldown_steps=2,
            correction_error_threshold=0.30,
        ),
        **CONDITIONS[condition_name],
    )
    workload = generate_workload(scenario, LENGTH, seed)
    result = run_experiment(workload, config)
    return {
        "scenario": scenario,
        "condition": condition_name,
        "readiness_delay_steps": delay,
        "seed": seed,
        "forecast_seed": forecast_seed,
        "workload": {"timestamps": workload.timestamps, "demand": workload.demand,
                     "signal_name": workload.signal_name, "unit": workload.unit},
        "simulation": result,
    }


def run(mode: str, output_name: str | None = None) -> Path:
    if mode not in {"pilot", "confirmatory"}:
        raise ValueError("mode must be pilot or confirmatory")
    seeds = (SEEDS[0],) if mode == "pilot" else SEEDS
    out = _new_output(output_name, mode)
    raw_path = out / "raw_trajectories.ndjson.gz"
    summary_path = out / "run_metrics.csv"
    total = len(SCENARIOS_ORDERED) * len(CONDITIONS) * len(DELAYS) * len(seeds)
    fields = ["scenario", "condition", "readiness_delay_steps", "seed", "forecast_seed", "policy", "steps",
              "capacity_violation_steps", "capacity_violation_rate", "total_unmet_demand", "total_excess_capacity",
              "mean_utilization", "forecast_mae", "forecast_rmse", "scale_up_replicas_requested",
              "scale_down_replicas_requested", "scale_churn_replicas", "replicas_activated", "simulated_capacity_time",
              "latency_slo_measured", "monetary_cost_measured"]
    started = datetime.now(timezone.utc)
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as raw_file, \
            summary_path.open("w", encoding="utf-8", newline="") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=fields)
        writer.writeheader()
        done = 0
        for scenario in SCENARIOS_ORDERED:
            for condition_name in CONDITIONS:
                for delay in DELAYS:
                    for seed in seeds:
                        record = _run_configuration(scenario, condition_name, delay, seed)
                        raw_file.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                        for policy_result in record["simulation"]["policies"]:
                            metrics = policy_result["metrics"]
                            writer.writerow({"scenario": scenario, "condition": condition_name,
                                             "readiness_delay_steps": delay, "seed": seed,
                                             "forecast_seed": record["forecast_seed"],
                                             "policy": policy_result["policy"], **metrics})
                        done += 1
                        if done % 12 == 0 or done == total:
                            print(f"{mode}: {done}/{total} paired configurations", flush=True)

    ended = datetime.now(timezone.utc)
    manifest = {
        "protocol": "HybridScale Research Protocol v1.0",
        "mode": mode,
        "confirmatory": mode == "confirmatory",
        "created_utc": started.isoformat(),
        "completed_utc": ended.isoformat(),
        "elapsed_seconds": round((ended - started).total_seconds(), 3),
        "command": "python experiments/run_study.py --mode " + mode,
        "code_revision": None,
        "code_revision_note": "No Git worktree was available at the starting audit.",
        "environment": {"python": platform.python_version(), "platform": platform.system()},
        "matrix": {"scenarios": list(SCENARIOS_ORDERED), "forecast_conditions": CONDITIONS,
                   "readiness_delay_steps": list(DELAYS), "seeds": list(seeds), "steps_per_workload": LENGTH,
                   "interval_seconds": INTERVAL_SECONDS, "policy_count": 3,
                   "paired_configurations": total, "policy_trajectories": total * 3,
                   "policy_steps": total * 3 * LENGTH},
        "files": {"raw": raw_path.name, "metrics": summary_path.name},
        "evidence_boundary": "Synthetic simulator capacity proxies only; no measured latency, SLO, monetary cost, trace, or Kubernetes outcomes.",
        "raw_record_format": "One gzip NDJSON record per paired workload/condition/delay/seed configuration; includes demand, simulator configuration, and all policy step rows.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pilot", "confirmatory"), required=True)
    parser.add_argument("--output-name", help="Optional new folder name under experiments/results")
    args = parser.parse_args()
    path = run(args.mode, args.output_name)
    print(f"Saved {args.mode} study artifacts under {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
