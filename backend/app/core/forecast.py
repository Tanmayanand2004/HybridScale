from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Sequence


@dataclass
class ForecastErrorTracker:
    window: int = 12
    errors: deque[float] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = deque(maxlen=self.window)

    def observe(self, prediction: float, actual: float) -> None:
        assert self.errors is not None
        self.errors.append(abs(actual - prediction))

    @property
    def mae(self) -> float | None:
        assert self.errors is not None
        return sum(self.errors) / len(self.errors) if self.errors else None

    def normalized_mae(self, demand_history: Sequence[float], epsilon: float = 1e-6) -> float | None:
        mae = self.mae
        if mae is None or not demand_history:
            return None
        scale = sum(demand_history[-self.window :]) / min(len(demand_history), self.window)
        return mae / max(scale, epsilon)


def persistence_forecast(history: Sequence[float], horizon: int = 1) -> float:
    """Last observation baseline. Caller must pass only observations available now."""
    if not history:
        return 0.0
    if horizon < 1:
        raise ValueError("horizon must be at least one step")
    return max(0.0, float(history[-1]))
