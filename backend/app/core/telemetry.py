from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: float | None
    observed_at: float | None
    max_age_seconds: float

    def state_at(self, now: float) -> str:
        if self.value is None or self.observed_at is None:
            return "missing"
        if self.observed_at > now or now - self.observed_at > self.max_age_seconds:
            return "stale"
        return "fresh"


def allow_scale_down(samples: list[MetricSample], required_names: set[str], now: float, slo_breached: bool) -> tuple[bool, list[str]]:
    states = {sample.name: sample.state_at(now) for sample in samples}
    absent = sorted(required_names - states.keys())
    if absent:
        return False, [f"missing_required:{name}" for name in absent]
    invalid = sorted(name for name in required_names if states.get(name) != "fresh")
    if invalid:
        return False, [f"non_fresh_required:{name}" for name in invalid]
    if slo_breached:
        return False, ["active_slo_breach"]
    return True, ["required_signals_fresh", "no_active_slo_breach"]
