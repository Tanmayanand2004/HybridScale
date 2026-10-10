from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    target_utilization: float = 0.70
    min_replicas: int = 1
    max_replicas: int = 20
    max_scale_up_step: int = 4
    max_scale_down_step: int = 2
    cooldown_steps: int = 2
    correction_error_threshold: float = 0.30
    reactive_sustain_steps: int = 1
    hybrid_current_safety_correction: bool = True
    hybrid_forecast_error_correction: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.target_utilization <= 1:
            raise ValueError("target_utilization must be in (0, 1]")
        if self.min_replicas < 0 or self.max_replicas < max(1, self.min_replicas):
            raise ValueError("invalid replica bounds")
        if min(self.max_scale_up_step, self.max_scale_down_step) < 1:
            raise ValueError("scale steps must be positive")
        if self.cooldown_steps < 0 or self.reactive_sustain_steps < 1:
            raise ValueError("invalid cooldown or sustain setting")


def demand_target(demand: float, config: PolicyConfig) -> int:
    return max(config.min_replicas, min(config.max_replicas, math.ceil(demand / config.target_utilization)))


def bounded_step(current: int, target: int, config: PolicyConfig, cooldown_remaining: int = 0) -> int:
    target = max(config.min_replicas, min(config.max_replicas, target))
    if cooldown_remaining > 0:
        return current
    if target > current:
        return min(target, current + config.max_scale_up_step)
    if target < current:
        return max(target, current - config.max_scale_down_step)
    return current


def reactive_target(current_demand: float, config: PolicyConfig) -> int:
    return demand_target(current_demand, config)


def predictive_target(forecast_demand: float, config: PolicyConfig) -> int:
    return demand_target(forecast_demand, config)


def hybrid_target(
    forecast_demand: float,
    current_demand: float,
    ready_replicas: int,
    normalized_mae: float | None,
    config: PolicyConfig,
) -> tuple[int, list[str]]:
    """Forecast proposes capacity; current load/error state can only correct upward."""
    proposed = predictive_target(forecast_demand, config)
    reasons = ["forecast_proposal"]
    observed_target = reactive_target(current_demand, config)
    corrected = proposed
    if config.hybrid_current_safety_correction and current_demand > ready_replicas * config.target_utilization:
        corrected = max(corrected, observed_target)
        reasons.append("current_load_safety_correction")
    if (config.hybrid_forecast_error_correction and normalized_mae is not None
            and normalized_mae >= config.correction_error_threshold):
        corrected = max(corrected, observed_target)
        reasons.append("recent_forecast_error_correction")
    return max(config.min_replicas, min(config.max_replicas, corrected)), reasons
