"""Streaming adapter for a user-selected Alibaba MS_Resource_Table CSV subset.

The full public trace is intentionally never downloaded by this application.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .workload import Workload


def load_alibaba_cpu_subset(
    path: str | Path,
    service_name: str,
    *,
    timestamp_column: str = "timestamp",
    service_column: str = "msname",
    cpu_column: str = "cpu_utilization",
    interval_ms: int = 60_000,
) -> Workload:
    """Aggregate a user-selected service subset in one pass.

    CPU fractions are summed across observed containers in each interval. This
    is a proxy under the assumption one utilization unit represents one
    replica's CPU capacity; it is not a request-rate signal.
    """
    if interval_ms <= 0 or not service_name:
        raise ValueError("interval_ms must be positive and service_name non-empty")
    totals: dict[int, float] = defaultdict(float)
    with Path(path).open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {timestamp_column, service_column, cpu_column}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"CSV must contain columns: {', '.join(sorted(required))}")
        for row_number, row in enumerate(reader, start=2):
            if row.get(service_column) != service_name:
                continue
            try:
                timestamp = int(float(row[timestamp_column]))
                cpu = float(row[cpu_column])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid timestamp or CPU value on CSV row {row_number}") from exc
            if timestamp < 0 or cpu < 0:
                raise ValueError(f"timestamp and CPU value must be non-negative on CSV row {row_number}")
            bucket = timestamp // interval_ms * interval_ms
            totals[bucket] += cpu
    if not totals:
        raise ValueError(f"no rows found for service {service_name!r}")
    timestamps = sorted(totals)
    return Workload(
        timestamps=timestamps,
        demand=[totals[t] for t in timestamps],
        signal_name="summed_container_cpu_utilization_proxy",
        unit="summed_cpu_utilization_units",
    )
