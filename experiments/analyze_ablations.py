"""Compare each correction ablation with the full hybrid from the main run."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (PROJECT_ROOT / "experiments" / "results").resolve()
MAIN_RUN = "v1_confirmatory_20261009"
METRICS = ("capacity_violation_rate", "total_unmet_demand", "simulated_capacity_time",
           "total_excess_capacity", "scale_churn_replicas")
ABLATIONS = ("without_current_load_correction", "without_forecast_error_correction")


def analyze(name: str, samples: int = 10_000) -> Path:
    source = (RESULT_ROOT / name).resolve()
    main_path = (RESULT_ROOT / MAIN_RUN).resolve()
    if RESULT_ROOT not in source.parents or not source.is_dir() or not main_path.is_dir():
        raise ValueError("provide an existing ablation folder and retain the main confirmatory run")
    main_manifest = json.loads((main_path / "manifest.json").read_text(encoding="utf-8"))
    ablation_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if not main_manifest.get("confirmatory") or not ablation_manifest.get("mode") == "predeclared_ablation":
        raise ValueError("analysis requires the saved main confirmatory run and an ablation run")

    full: dict[tuple[str, str, int, int], dict[str, float]] = {}
    with (main_path / main_manifest["files"]["metrics"]).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["policy"] == "hybrid":
                key = (row["scenario"], row["condition"], int(row["readiness_delay_steps"]), int(row["seed"]))
                full[key] = {metric: float(row[metric]) for metric in METRICS}
    values: dict[tuple[str, str, int, int, str], dict[str, float]] = {}
    with (source / ablation_manifest["files"]["metrics"]).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["scenario"], row["condition"], int(row["readiness_delay_steps"]), int(row["seed"]), row["ablation"])
            if row["ablation"] not in ABLATIONS or key in values:
                raise ValueError(f"duplicate or unknown ablation row {key}")
            values[key] = {metric: float(row[metric]) for metric in METRICS}
    if len(full) != 3240 or len(values) != 6480:
        raise ValueError(f"unexpected run counts: {len(full)} main and {len(values)} ablation metric rows")
    cells = sorted({key[:3] for key in full})
    rng = np.random.default_rng(20261009)
    detailed_rows: list[dict[str, object]] = []
    aggregate_rows: list[dict[str, object]] = []
    for ablation in ABLATIONS:
        for metric in METRICS:
            base_arr = np.asarray([full[(*cell, seed)][metric] for cell in cells for seed in range(1000, 1030)], dtype=float)
            abl_arr = np.asarray([values[(*cell, seed, ablation)][metric] for cell in cells for seed in range(1000, 1030)], dtype=float)
            delta = abl_arr - base_arr
            aggregate_rows.append({"ablation": ablation, "metric": metric,
                                   "full_hybrid_mean": float(base_arr.mean()),
                                   "ablated_hybrid_mean": float(abl_arr.mean()),
                                   "ablation_minus_full_mean": float(delta.mean())})
        for cell in cells:
            scenario, condition, delay = cell
            seed_ids = range(1000, 1030)
            indices = rng.integers(0, 30, size=(samples, 30))
            row: dict[str, object] = {"scenario": scenario, "condition": condition,
                                      "readiness_delay_steps": delay, "ablation": ablation, "n_seeds": 30}
            for metric in METRICS:
                diff = np.asarray([values[(*cell, seed, ablation)][metric] - full[(*cell, seed)][metric]
                                   for seed in seed_ids], dtype=float)
                bootstrap_means = diff[indices].mean(axis=1)
                row.update({f"{metric}_mean_difference": float(diff.mean()),
                            f"{metric}_ci95_low": float(np.percentile(bootstrap_means, 2.5)),
                            f"{metric}_ci95_high": float(np.percentile(bootstrap_means, 97.5))})
            detailed_rows.append(row)

    out = source / "analysis"
    out.mkdir(exist_ok=False)
    with (out / "ablation_aggregate_summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(aggregate_rows[0]))
        writer.writeheader()
        writer.writerows(aggregate_rows)
    with (out / "paired_ablation_cells.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(detailed_rows[0]))
        writer.writeheader()
        writer.writerows(detailed_rows)
    report = {
        "input_main_run": MAIN_RUN, "input_ablations": name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "paired_cell_count": len(cells), "seeds_per_cell": 30,
        "bootstrap": {"method": "paired percentile bootstrap over seeds within each cell", "samples": samples,
                      "confidence_level": 0.95, "analysis_seed": 20261009},
        "outputs": ["ablation_aggregate_summary.csv", "paired_ablation_cells.csv"],
        "interpretation": "Ablation minus full HybridScale; lower is better for every listed metric. Synthetic proxies only.",
    }
    (out / "analysis_manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ablation_directory")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()
    if args.bootstrap_samples < 1000:
        raise SystemExit("use at least 1,000 bootstrap resamples")
    print(f"Saved ablation analysis to {analyze(args.ablation_directory, args.bootstrap_samples).relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
