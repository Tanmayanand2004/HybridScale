"""Check structure and paired-input integrity of a completed study directory."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (PROJECT_ROOT / "experiments" / "results").resolve()


def audit(name: str) -> dict[str, int | str]:
    path = (RESULT_ROOT / name).resolve()
    if RESULT_ROOT not in path.parents or not path.is_dir():
        raise ValueError("study directory must be an existing child of experiments/results")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    records = 0
    policy_trajectories = 0
    with gzip.open(path / manifest["files"]["raw"], "rt", encoding="utf-8") as raw_file:
        for line_number, line in enumerate(raw_file, start=1):
            record = json.loads(line)
            policies = record["simulation"]["policies"]
            if len(policies) != 3 or {p["policy"] for p in policies} != {"reactive", "predictive", "hybrid"}:
                raise ValueError(f"invalid policy set on raw record {line_number}")
            reference = policies[0]["steps"]
            if not all(len(p["steps"]) == len(reference) for p in policies):
                raise ValueError(f"policy trajectory length mismatch on raw record {line_number}")
            for index in range(len(reference)):
                row = reference[index]
                if not all(p["steps"][index]["demand"] == row["demand"] for p in policies):
                    raise ValueError(f"demand mismatch on raw record {line_number}, step {index}")
                forecasts = [p["steps"][index]["forecast"] for p in policies]
                if not forecasts[0] == forecasts[1] == forecasts[2]:
                    raise ValueError(f"forecast stream mismatch on raw record {line_number}, step {index}")
            records += 1
            policy_trajectories += len(policies)
    with (path / manifest["files"]["metrics"]).open("r", encoding="utf-8", newline="") as metrics_file:
        rows = list(csv.DictReader(metrics_file))
    expected_records = manifest["matrix"]["paired_configurations"]
    if records != expected_records or len(rows) != expected_records * 3:
        raise ValueError(f"manifest/row count mismatch: {records} raw records, {len(rows)} summary rows")
    for row in rows:
        rate = float(row["capacity_violation_rate"])
        if not 0 <= rate <= 1:
            raise ValueError("capacity violation rate outside [0, 1]")
        if row["latency_slo_measured"] != "False" or row["monetary_cost_measured"] != "False":
            raise ValueError("unexpected latency or monetary measurement flag")
    return {"status": "passed", "paired_configurations": records,
            "policy_trajectories": policy_trajectories, "metric_rows": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_directory", help="folder name under experiments/results")
    args = parser.parse_args()
    print(json.dumps(audit(args.study_directory), indent=2))


if __name__ == "__main__":
    main()
