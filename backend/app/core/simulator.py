from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from .forecast import ForecastErrorTracker, persistence_forecast
from .policies import PolicyConfig, bounded_step, hybrid_target, predictive_target, reactive_target
from .workload import Workload

POLICIES = ("reactive", "predictive", "hybrid")


@dataclass(frozen=True)
class SimulationConfig:
    interval_seconds: int = 60
    initial_replicas: int = 2
    readiness_delay_steps: int = 2
    forecast_horizon_steps: int = 2
    forecast_bias: float = 0.0
    forecast_noise_std: float = 0.0
    forecast_lag_steps: int = 0
    forecast_degradation_start_step: int | None = None
    forecast_degradation_bias: float = 0.0
    forecast_seed: int = 42
    policy: PolicyConfig = PolicyConfig()

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0 or self.readiness_delay_steps < 0 or self.forecast_horizon_steps < 1 or self.forecast_lag_steps < 0 or self.forecast_noise_std < 0:
            raise ValueError("invalid interval or horizon")
        if self.forecast_degradation_start_step is not None and self.forecast_degradation_start_step < 0:
            raise ValueError("forecast degradation step must be non-negative")
        if not self.policy.min_replicas <= self.initial_replicas <= self.policy.max_replicas:
            raise ValueError("initial replicas must be within configured bounds")


def _simulate_one(workload: Workload, name: str, config: SimulationConfig) -> dict[str, Any]:
    ready = config.initial_replicas
    desired = ready
    pending: list[tuple[int, int]] = []
    last_change = -10**9
    tracker = ForecastErrorTracker()
    issued: dict[int, tuple[int, float]] = {}
    evaluated_forecast_errors: list[float] = []
    evaluated_forecast_squared_errors: list[float] = []
    history: list[float] = []
    forecast_rng = random.Random(config.forecast_seed)
    rows: list[dict[str, Any]] = []
    activated = 0
    scaled_up = 0
    scaled_down = 0
    churn = 0

    for step, demand in enumerate(workload.demand):
        just_ready = 0
        remaining: list[tuple[int, int]] = []
        for ready_at, count in pending:
            if ready_at <= step:
                ready += count
                just_ready += count
                activated += count
            else:
                remaining.append((ready_at, count))
        pending = remaining

        matured = issued.pop(step, None)
        if matured:
            issued_at, predicted = matured
            tracker.observe(predicted, demand)
            evaluated_forecast_errors.append(abs(demand - predicted))
            evaluated_forecast_squared_errors.append((demand - predicted) ** 2)

        history.append(demand)
        horizon = max(config.forecast_horizon_steps, config.readiness_delay_steps or 1)
        lagged_history = history[: max(1, len(history) - config.forecast_lag_steps)]
        forecast = persistence_forecast(lagged_history, horizon)
        bias = config.forecast_bias
        if config.forecast_degradation_start_step is not None and step >= config.forecast_degradation_start_step:
            bias += config.forecast_degradation_bias
        forecast = max(0.0, forecast * (1.0 + bias) + forecast_rng.gauss(0.0, config.forecast_noise_std))
        target_time = step + horizon
        issued[target_time] = (step, forecast)
        nmae = tracker.normalized_mae(history)

        if name == "reactive":
            raw_target = reactive_target(demand, config.policy)
            reasons = ["current_metric_target"]
        elif name == "predictive":
            raw_target = predictive_target(forecast, config.policy)
            reasons = ["forecast_proposal"]
        else:
            raw_target, reasons = hybrid_target(forecast, demand, ready, nmae, config.policy)

        cooldown = config.policy.cooldown_steps - (step - last_change)
        next_desired = bounded_step(desired, raw_target, config.policy, max(0, cooldown))
        previous_desired = desired
        decision = next_desired
        requested_delta = decision - previous_desired
        activated_now = 0
        if requested_delta != 0:
            churn += abs(requested_delta)
            if requested_delta > 0:
                added = requested_delta
                scaled_up += added
                if config.readiness_delay_steps == 0:
                    ready += added
                    activated += added
                    activated_now = added
                else:
                    pending.append((step + config.readiness_delay_steps, added))
            else:
                remove = -requested_delta
                scaled_down += remove
                # Cancel not-yet-ready capacity first, latest activation first.
                pending.sort(key=lambda item: item[0], reverse=True)
                cancelled = 0
                adjusted: list[tuple[int, int]] = []
                for ready_at, count in pending:
                    take = min(remove - cancelled, count)
                    cancelled += take
                    if count > take:
                        adjusted.append((ready_at, count - take))
                pending = adjusted
                ready = max(0, ready - (remove - cancelled))
            desired = decision
            last_change = step

        capacity = float(ready)
        shortfall = max(0.0, demand - capacity)
        excess = max(0.0, capacity - demand)
        utilization = min(1.0, demand / capacity) if capacity > 0 else (1.0 if demand > 0 else 0.0)
        rows.append({
            "step": step,
            "timestamp": workload.timestamps[step],
            "demand": round(demand, 6),
            "forecast": round(forecast, 6),
            "forecast_target_step": target_time,
            "forecast_error_mae": round(tracker.mae, 6) if tracker.mae is not None else None,
            "forecast_nmae": round(nmae, 6) if nmae is not None else None,
            "ready_replicas": ready,
            "desired_replicas": desired,
            "pending_replicas": sum(count for _, count in pending),
            "activated_this_step": just_ready + activated_now,
            "requested_delta": requested_delta,
            "policy_target": raw_target,
            "reasons": reasons,
            "capacity": capacity,
            "capacity_violation": demand > capacity,
            "unmet_demand": round(shortfall, 6),
            "excess_capacity": round(excess, 6),
            "utilization": round(utilization, 6),
        })

    n = len(rows)
    violation_steps = sum(bool(r["capacity_violation"]) for r in rows)
    metrics = {
        "steps": n,
        "capacity_violation_steps": violation_steps,
        "capacity_violation_rate": violation_steps / n if n else 0.0,
        "total_unmet_demand": sum(r["unmet_demand"] for r in rows),
        "total_excess_capacity": sum(r["excess_capacity"] for r in rows),
        "mean_utilization": sum(r["utilization"] for r in rows) / n if n else 0.0,
        "forecast_mae": sum(evaluated_forecast_errors) / len(evaluated_forecast_errors) if evaluated_forecast_errors else None,
        "forecast_rmse": math.sqrt(sum(evaluated_forecast_squared_errors) / len(evaluated_forecast_squared_errors)) if evaluated_forecast_squared_errors else None,
        "scale_up_replicas_requested": scaled_up,
        "scale_down_replicas_requested": scaled_down,
        "scale_churn_replicas": churn,
        "replicas_activated": activated,
        "simulated_capacity_time": sum(r["ready_replicas"] for r in rows) * config.interval_seconds,
        "latency_slo_measured": False,
        "monetary_cost_measured": False,
    }
    return {"policy": name, "metrics": metrics, "steps": rows}


def run_experiment(workload: Workload, config: SimulationConfig) -> dict[str, Any]:
    policies = [_simulate_one(workload, name, config) for name in POLICIES]
    return {
        "result_type": "simulation",
        "workload": {"steps": len(workload.demand), "signal_name": workload.signal_name, "unit": workload.unit},
        "config": {**asdict(config), "policy": asdict(config.policy)},
        "policies": policies,
        "limitations": [
            "Capacity-proxy evaluation only; no application latency is simulated.",
            "Demand is expressed in abstract replica-capacity units.",
            "Persistence forecast is an engineering baseline, not a selected production model.",
        ],
    }
