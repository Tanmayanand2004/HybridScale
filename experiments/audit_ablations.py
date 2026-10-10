"""Audit the raw trajectories and pairing for a correction-ablation run."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (PROJECT_ROOT / "experiments" / "results").resolve()
EXPECTED = {"without_current_load_correction", "without_forecast_error_correction"}


def audit(name: str) -> dict[str, int | str]:
    path = (RESULT_ROOT / name).resolve()
    if RESULT_ROOT not in path.parents or not path.is_dir():
        raise ValueError("ablation directory must be an existing child of experiments/results")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    pending: dict[tuple[str, str, int, int], tuple[str, list[dict[str, object]], list[float]]] = {}
    count = 0
    with gzip.open(path / manifest["files"]["raw"], "rt", encoding="utf-8") as raw:
        for line_number, line in enumerate(raw, 1):
            record = json.loads(line)
            key = (record["scenario"], record["condition"], record["readiness_delay_steps"], record["seed"])
            variant = record["ablation"]
            if variant not in EXPECTED:
                raise ValueError(f"unexpected ablation variant on record {line_number}")
            policy_config = record["simulation_config"]["policy"]
            if variant == "without_current_load_correction" and policy_config["hybrid_current_safety_correction"] is not False:
                raise ValueError(f"current-load correction was not disabled on record {line_number}")
            if variant == "without_forecast_error_correction" and policy_config["hybrid_forecast_error_correction"] is not False:
                raise ValueError(f"forecast-error correction was not disabled on record {line_number}")
            result = record["policy_result"]
            if result["policy"] != "hybrid" or len(result["steps"]) != 240:
                raise ValueError(f"invalid hybrid trajectory on record {line_number}")
            demand = [round(value, 6) for value in record["demand"]]
            step_demand = [row["demand"] for row in result["steps"]]
            forecasts = [row["forecast"] for row in result["steps"]]
            if demand != step_demand:
                raise ValueError(f"workload and trajectory demand differ on record {line_number}")
            if key not in pending:
                pending[key] = (variant, result["steps"], forecasts)
            else:
                prior_variant, prior_steps, prior_forecasts = pending.pop(key)
                if prior_variant == variant or prior_steps[0]["demand"] != result["steps"][0]["demand"]:
                    raise ValueError(f"duplicate/mismatched ablation pair on record {line_number}")
                if prior_forecasts != forecasts:
                    raise ValueError(f"forecast streams differ across ablation variants for {key}")
            count += 1
    if pending:
        raise ValueError(f"{len(pending)} ablation configurations are missing their paired variant")
    with (path / manifest["files"]["metrics"]).open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    expected_rows = manifest["policy_trajectories"]
    if count != expected_rows or len(rows) != expected_rows:
        raise ValueError(f"manifest/row count mismatch: {count} raw and {len(rows)} metric records")
    if {row["ablation"] for row in rows} != EXPECTED:
        raise ValueError("summary metrics are missing an ablation variant")
    return {"status": "passed", "ablation_trajectories": count,
            "paired_configurations": count // len(EXPECTED), "metric_rows": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ablation_directory")
    args = parser.parse_args()
    print(json.dumps(audit(args.ablation_directory), indent=2))


if __name__ == "__main__":
    main()
