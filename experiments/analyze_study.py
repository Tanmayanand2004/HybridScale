"""Generate protocol-v1 per-cell summaries, paired CIs, and a vector heatmap."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (PROJECT_ROOT / "experiments" / "results").resolve()
METRICS = ("capacity_violation_rate", "total_unmet_demand", "simulated_capacity_time",
           "total_excess_capacity", "scale_churn_replicas", "forecast_mae")
CONTRAST_METRICS = METRICS[:-1]
POLICIES = ("reactive", "predictive", "hybrid")
BASELINES = ("reactive", "predictive")
SCENARIOS = ("stable", "gradual", "burst", "periodic", "volatile", "shift")
CONDITIONS = ("clean", "underpredict_25pct", "overpredict_25pct", "noise_0_5", "stale_1_step", "degraded_after_step_120")


def _safe_child(name: str) -> Path:
    path = (RESULT_ROOT / name).resolve()
    if RESULT_ROOT not in path.parents or not path.is_dir():
        raise ValueError("study directory must be an existing child of experiments/results")
    return path


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(path: Path, width: int, height: int, commands: list[str]) -> None:
    content = ("\n".join(commands) + "\n").encode("ascii", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode())
        pdf.extend(obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(pdf)


def _heatmap_svg_pdf(output: Path, grid: dict[tuple[str, str], float], delay: int) -> None:
    width, height = 960, 560
    left, top, cell_w, cell_h = 210, 100, 112, 54
    values = list(grid.values())
    limit = max(0.01, max(abs(v) for v in values))

    def rgb(value: float) -> tuple[float, float, float]:
        magnitude = min(1.0, abs(value) / limit)
        white = (0.97, 0.97, 0.97)
        endpoint = (0.12, 0.34, 0.72) if value < 0 else (0.78, 0.20, 0.16)
        return tuple(white[i] * (1.0 - magnitude) + endpoint[i] * magnitude for i in range(3))

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="480" y="34" text-anchor="middle" font-family="Arial" font-size="20">HybridScale − reactive: capacity-violation rate</text>',
           f'<text x="480" y="60" text-anchor="middle" font-family="Arial" font-size="13">Readiness delay = {delay} steps; paired mean difference over 30 seeds (negative favors HybridScale)</text>']
    commands: list[str] = ["1 1 1 rg 0 0 960 560 re f", "0 0 0 rg"]

    def pdf_text(x: float, y_top: float, text: str, size: int = 10, align: str = "left") -> None:
        # PDF uses bottom-left origin; SVG uses top-left. Approximate centered labels.
        if align == "center":
            x -= len(text) * size * 0.25
        elif align == "right":
            x -= len(text) * size * 0.52
        y = height - y_top
        commands.append("0 0 0 rg")
        commands.append(f"BT /F1 {size} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_pdf_escape(text)}) Tj ET")

    pdf_text(480, 34, "HybridScale - reactive: capacity-violation rate", 17, "center")
    pdf_text(480, 58, f"Readiness delay = {delay} steps; paired mean difference over 30 seeds (negative favors HybridScale)", 10, "center")
    for col, condition in enumerate(CONDITIONS):
        x = left + col * cell_w
        label = condition.replace("_", " ")
        svg.append(f'<text x="{x+cell_w/2}" y="88" text-anchor="middle" font-family="Arial" font-size="10">{label}</text>')
        pdf_text(x + cell_w / 2, 88, label, 8, "center")
    for row, scenario in enumerate(SCENARIOS):
        y = top + row * cell_h
        svg.append(f'<text x="{left-14}" y="{y+cell_h/2+4}" text-anchor="end" font-family="Arial" font-size="12">{scenario}</text>')
        pdf_text(left - 14, y + cell_h / 2 + 4, scenario, 11, "right")
        for col, condition in enumerate(CONDITIONS):
            value = grid[(scenario, condition)]
            r, g, b = rgb(value)
            x = left + col * cell_w
            fill = f"#{round(r*255):02x}{round(g*255):02x}{round(b*255):02x}"
            svg.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#ffffff"/>')
            svg.append(f'<text x="{x+cell_w/2}" y="{y+cell_h/2+4}" text-anchor="middle" font-family="Arial" font-size="12">{value:+.3f}</text>')
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x} {height-y-cell_h} {cell_w} {cell_h} re f")
            commands.append(f"1 1 1 RG 0.8 w {x} {height-y-cell_h} {cell_w} {cell_h} re S")
            pdf_text(x + cell_w / 2, y + cell_h / 2 + 4, f"{value:+.3f}", 11, "center")
    svg.extend(['<text x="480" y="530" text-anchor="middle" font-family="Arial" font-size="11">Forecast impairment condition</text>', '</svg>'])
    pdf_text(480, 530, "Forecast impairment condition", 10, "center")
    (output / f"capacity_violation_heatmap_delay_{delay}.svg").write_text("\n".join(svg), encoding="utf-8")
    _write_pdf(output / f"capacity_violation_heatmap_delay_{delay}.pdf", width, height, commands)


def analyze(name: str, bootstrap_samples: int = 10_000) -> Path:
    source = _safe_child(name)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("mode") != "confirmatory" or not manifest.get("confirmatory"):
        raise ValueError("analysis is restricted to a completed confirmatory run; pilot outcomes are excluded")
    values: dict[tuple[str, str, int, int, str], dict[str, float]] = {}
    with (source / manifest["files"]["metrics"]).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["scenario"], row["condition"], int(row["readiness_delay_steps"]), int(row["seed"]))
            policy = row["policy"]
            if policy not in POLICIES or policy in values.setdefault(key, {}):
                raise ValueError(f"duplicate or unknown policy for {key}")
            values[key][policy] = {metric: (float(row[metric]) if row[metric] else math.nan) for metric in METRICS}  # type: ignore[assignment]

    grouped: dict[tuple[str, str, int], dict[str, dict[int, dict[str, float]]]] = defaultdict(lambda: defaultdict(dict))
    for (scenario, condition, delay, seed), policy_values in values.items():
        if set(policy_values) != set(POLICIES):
            raise ValueError(f"incomplete policy set for {scenario}/{condition}/{delay}/{seed}")
        for policy, metrics in policy_values.items():
            grouped[(scenario, condition, delay)][policy][seed] = metrics

    out = source / "analysis"
    out.mkdir(exist_ok=False)
    policy_fields = ["scenario", "condition", "readiness_delay_steps", "policy", "n_seeds"]
    for metric in METRICS:
        policy_fields.extend([f"{metric}_mean", f"{metric}_median", f"{metric}_q25", f"{metric}_q75"])
    contrast_fields = ["scenario", "condition", "readiness_delay_steps", "contrast", "n_seeds"]
    for metric in CONTRAST_METRICS:
        contrast_fields.extend([f"{metric}_mean_difference", f"{metric}_ci95_low", f"{metric}_ci95_high"])

    analysis_seed = 20261009
    rng = np.random.default_rng(analysis_seed)
    policy_rows: list[dict[str, object]] = []
    contrast_rows: list[dict[str, object]] = []
    cell_order = sorted(grouped, key=lambda key: (SCENARIOS.index(key[0]), CONDITIONS.index(key[1]), key[2]))
    for cell_idx, cell in enumerate(cell_order):
        scenario, condition, delay = cell
        seed_lists = [set(grouped[cell][policy]) for policy in POLICIES]
        if not seed_lists[0] == seed_lists[1] == seed_lists[2] or len(seed_lists[0]) != 30:
            raise ValueError(f"expected the same 30 seeds for all policies in {cell}")
        seeds = sorted(seed_lists[0])
        for policy in POLICIES:
            row: dict[str, object] = {"scenario": scenario, "condition": condition,
                                      "readiness_delay_steps": delay, "policy": policy, "n_seeds": len(seeds)}
            for metric in METRICS:
                arr = np.asarray([grouped[cell][policy][seed][metric] for seed in seeds], dtype=float)
                row.update({f"{metric}_mean": float(np.mean(arr)), f"{metric}_median": float(np.median(arr)),
                            f"{metric}_q25": float(np.percentile(arr, 25)), f"{metric}_q75": float(np.percentile(arr, 75))})
            policy_rows.append(row)
        sample_indices = rng.integers(0, len(seeds), size=(bootstrap_samples, len(seeds)))
        for baseline in BASELINES:
            row = {"scenario": scenario, "condition": condition, "readiness_delay_steps": delay,
                   "contrast": f"hybrid_minus_{baseline}", "n_seeds": len(seeds)}
            for metric in CONTRAST_METRICS:
                paired = np.asarray([grouped[cell]["hybrid"][seed][metric] - grouped[cell][baseline][seed][metric]
                                     for seed in seeds], dtype=float)
                boot_means = paired[sample_indices].mean(axis=1)
                row.update({f"{metric}_mean_difference": float(paired.mean()),
                            f"{metric}_ci95_low": float(np.percentile(boot_means, 2.5)),
                            f"{metric}_ci95_high": float(np.percentile(boot_means, 97.5))})
            contrast_rows.append(row)

    with (out / "policy_cell_summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=policy_fields)
        writer.writeheader()
        writer.writerows(policy_rows)
    with (out / "paired_contrasts.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=contrast_fields)
        writer.writeheader()
        writer.writerows(contrast_rows)
    for delay in (0, 2, 4):
        delay_grid: dict[tuple[str, str], float] = {}
        for scenario in SCENARIOS:
            for condition in CONDITIONS:
                record = next(row for row in contrast_rows if row["scenario"] == scenario and row["condition"] == condition
                              and row["readiness_delay_steps"] == delay and row["contrast"] == "hybrid_minus_reactive")
                delay_grid[(scenario, condition)] = float(record["capacity_violation_rate_mean_difference"])
        _heatmap_svg_pdf(out, delay_grid, delay)
    report = {
        "protocol": manifest["protocol"], "input_run": name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bootstrap": {"method": "paired percentile bootstrap over seed-level differences", "samples": bootstrap_samples,
                      "confidence_level": 0.95, "analysis_seed": analysis_seed},
        "cells": len(cell_order), "seeds_per_cell": 30,
        "policy_summary_rows": len(policy_rows), "paired_contrast_rows": len(contrast_rows),
        "metrics": list(METRICS),
        "interpretation": "Negative paired differences favor HybridScale only for lower-is-better metrics. Simulator capacity proxies only; no latency/SLO/cost claims.",
        "outputs": ["policy_cell_summary.csv", "paired_contrasts.csv"] +
                   [f"capacity_violation_heatmap_delay_{delay}.{suffix}" for delay in (0, 2, 4) for suffix in ("svg", "pdf")],
    }
    (out / "analysis_manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_directory")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()
    if args.bootstrap_samples < 1000:
        raise SystemExit("use at least 1,000 bootstrap resamples")
    output = analyze(args.study_directory, args.bootstrap_samples)
    print(f"Saved analysis to {output.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
