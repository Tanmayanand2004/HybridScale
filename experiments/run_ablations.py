"""Run the two preregistered HybridScale correction ablations."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.policies import PolicyConfig  # noqa: E402
from backend.app.core.simulator import SimulationConfig, _simulate_one  # noqa: E402
from backend.app.core.workload import generate_workload  # noqa: E402
from experiments.run_study import CONDITIONS, DELAYS, INTERVAL_SECONDS, LENGTH, SCENARIOS_ORDERED, SEEDS  # noqa: E402

ABLATIONS = {
    "without_current_load_correction": {"hybrid_current_safety_correction": False},
    "without_forecast_error_correction": {"hybrid_forecast_error_correction": False},
}


def run(output_name: str) -> Path:
    if not output_name or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in output_name):
        raise ValueError("output name may contain only letters, digits, underscores, and hyphens")
    root = (PROJECT_ROOT / "experiments" / "results").resolve()
    out = (root / output_name).resolve()
    if root not in out.parents:
        raise ValueError("output must stay inside experiments/results")
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc)
    total = len(SCENARIOS_ORDERED) * len(CONDITIONS) * len(DELAYS) * len(SEEDS) * len(ABLATIONS)
    metric_fields = ["scenario", "condition", "readiness_delay_steps", "seed", "forecast_seed", "ablation",
                     "steps", "capacity_violation_steps", "capacity_violation_rate", "total_unmet_demand",
                     "total_excess_capacity", "mean_utilization", "forecast_mae", "forecast_rmse",
                     "scale_up_replicas_requested", "scale_down_replicas_requested", "scale_churn_replicas",
                     "replicas_activated", "simulated_capacity_time", "latency_slo_measured", "monetary_cost_measured"]
    done = 0
    raw_path = out / "ablation_trajectories.ndjson.gz"
    metrics_path = out / "ablation_metrics.csv"
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as raw, \
            metrics_path.open("w", encoding="utf-8", newline="") as metric_file:
        writer = csv.DictWriter(metric_file, fieldnames=metric_fields)
        writer.writeheader()
        for scenario in SCENARIOS_ORDERED:
            for condition_name, disturbance in CONDITIONS.items():
                condition_index = list(CONDITIONS).index(condition_name)
                for delay in DELAYS:
                    for seed in SEEDS:
                        workload = generate_workload(scenario, LENGTH, seed)
                        forecast_seed = seed * 1009 + condition_index
                        for ablation, disabled in ABLATIONS.items():
                            policy = PolicyConfig(
                                target_utilization=0.70, min_replicas=1, max_replicas=20,
                                max_scale_up_step=4, max_scale_down_step=2, cooldown_steps=2,
                                correction_error_threshold=0.30, **disabled,
                            )
                            config = SimulationConfig(
                                interval_seconds=INTERVAL_SECONDS, initial_replicas=2,
                                readiness_delay_steps=delay, forecast_horizon_steps=2,
                                forecast_seed=forecast_seed, policy=policy, **disturbance,
                            )
                            result = _simulate_one(workload, "hybrid", config)
                            raw.write(json.dumps({
                                "scenario": scenario, "condition": condition_name,
                                "readiness_delay_steps": delay, "seed": seed,
                                "forecast_seed": forecast_seed, "ablation": ablation,
                                "timestamps": workload.timestamps, "demand": workload.demand,
                                "simulation_config": {**json.loads(json.dumps(config, default=lambda o: o.__dict__))},
                                "policy_result": result,
                            }, separators=(",", ":"), allow_nan=False) + "\n")
                            writer.writerow({"scenario": scenario, "condition": condition_name,
                                             "readiness_delay_steps": delay, "seed": seed,
                                             "forecast_seed": forecast_seed, "ablation": ablation,
                                             **result["metrics"]})
                            done += 1
                            if done % 120 == 0 or done == total:
                                print(f"ablations: {done}/{total} policy trajectories", flush=True)
    ended = datetime.now(timezone.utc)
    manifest = {
        "protocol": "HybridScale Research Protocol v1.0 planned correction ablations",
        "mode": "predeclared_ablation", "confirmatory_primary_matrix": False,
        "created_utc": started.isoformat(), "completed_utc": ended.isoformat(),
        "elapsed_seconds": round((ended - started).total_seconds(), 3),
        "command": f"python experiments/run_ablations.py --output-name {output_name}",
        "ablation_variants": list(ABLATIONS), "baseline": "hybrid policy from v1_confirmatory_20261009",
        "paired_configurations_per_variant": len(SCENARIOS_ORDERED) * len(CONDITIONS) * len(DELAYS) * len(SEEDS),
        "policy_trajectories": total, "steps_per_trajectory": LENGTH,
        "files": {"raw": raw_path.name, "metrics": metrics_path.name},
        "interpretation_boundary": "Synthetic capacity proxies only. Ablations isolate one correction signal at a time and do not tune thresholds.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    result = run(args.output_name)
    print(f"Saved correction ablations under {result.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
