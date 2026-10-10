from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Workload:
    timestamps: list[int]
    demand: list[float]
    signal_name: str = "request_rate_equivalent"
    unit: str = "replica_capacity_units"

    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.demand) or not self.demand:
            raise ValueError("timestamps and demand must have the same non-zero length")
        if any(not math.isfinite(x) or x < 0 for x in self.demand):
            raise ValueError("demand values must be finite and non-negative")
        if any(b <= a for a, b in zip(self.timestamps, self.timestamps[1:])):
            raise ValueError("timestamps must be strictly increasing")


SCENARIOS = {"stable", "gradual", "burst", "periodic", "volatile", "shift"}


def generate_workload(
    scenario: str = "burst", length: int = 120, seed: int = 42
) -> Workload:
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {sorted(SCENARIOS)}")
    if length < 10:
        raise ValueError("length must be at least 10 steps")
    rng = random.Random(seed)
    values: list[float] = []
    for i in range(length):
        phase = i / max(1, length - 1)
        if scenario == "stable":
            base, noise = 2.4, 0.12
        elif scenario == "gradual":
            base, noise = 1.0 + 4.2 * phase, 0.18
            if phase > 0.72:
                base = 1.0 + 4.2 * (1 - phase)
        elif scenario == "burst":
            base = 1.6 if phase < 0.38 else (7.0 if phase < 0.5 else 2.1)
            noise = 0.22
        elif scenario == "periodic":
            base = 3.0 + 1.5 * math.sin(2.0 * math.pi * i / 24.0)
            noise = 0.15
        elif scenario == "volatile":
            base, noise = 3.2 + 1.1 * math.sin(i * 0.7), 0.65
        else:  # a persistent level shift
            base, noise = (1.5 if phase < 0.5 else 5.0), 0.2
        values.append(max(0.0, base + rng.gauss(0.0, noise)))
    return Workload(list(range(length)), values)


def load_workload_csv(path: str | Path, timestamp_column: str = "timestamp", demand_column: str = "demand") -> Workload:
    timestamps: list[int] = []
    demand: list[float] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or timestamp_column not in reader.fieldnames or demand_column not in reader.fieldnames:
            raise ValueError(f"CSV must contain {timestamp_column!r} and {demand_column!r} columns")
        for row_number, row in enumerate(reader, start=2):
            try:
                timestamps.append(int(float(row[timestamp_column])))
                demand.append(float(row[demand_column]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid timestamp or demand on CSV row {row_number}") from exc
    return Workload(timestamps, demand)


def write_workload_csv(workload: Workload, path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "demand"])
        writer.writerows(zip(workload.timestamps, workload.demand))
