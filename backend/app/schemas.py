from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class PolicySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_utilization: float = Field(default=0.70, gt=0, le=1)
    min_replicas: int = Field(default=1, ge=0)
    max_replicas: int = Field(default=20, ge=1)
    max_scale_up_step: int = Field(default=4, ge=1)
    max_scale_down_step: int = Field(default=2, ge=1)
    cooldown_steps: int = Field(default=2, ge=0)
    correction_error_threshold: float = Field(default=0.30, ge=0)
    reactive_sustain_steps: int = Field(default=1, ge=1)
    hybrid_current_safety_correction: bool = True
    hybrid_forecast_error_correction: bool = True


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_seconds: int = Field(default=60, ge=1)
    initial_replicas: int = Field(default=2, ge=0)
    readiness_delay_steps: int = Field(default=2, ge=0)
    forecast_horizon_steps: int = Field(default=2, ge=1)
    forecast_bias: float = Field(default=0.0, ge=-1, le=5)
    forecast_noise_std: float = Field(default=0.0, ge=0)
    forecast_lag_steps: int = Field(default=0, ge=0, le=100_000)
    forecast_degradation_start_step: int | None = Field(default=None, ge=0)
    forecast_degradation_bias: float = Field(default=0.0, ge=-1, le=5)
    forecast_seed: int = 42
    policy: PolicySettings = Field(default_factory=PolicySettings)


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamps: list[int] = Field(min_length=1, max_length=100_000)
    demand: list[float] = Field(min_length=1, max_length=100_000)
    signal_name: str = "request_rate_equivalent"
    unit: str = "replica_capacity_units"
    scenario: str = "user_supplied"
    seed: int | None = None
    config: RunConfig = Field(default_factory=RunConfig)


class SyntheticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = "burst"
    length: int = Field(default=120, ge=10, le=100_000)
    seed: int = 42
    config: RunConfig = Field(default_factory=RunConfig)
