from backend.app.core.forecast import ForecastErrorTracker, persistence_forecast
from backend.app.core.policies import PolicyConfig, bounded_step, hybrid_target
from backend.app.core.simulator import SimulationConfig, run_experiment
from backend.app.core.telemetry import MetricSample, allow_scale_down
from backend.app.core.workload import Workload, generate_workload


def test_alibaba_adapter_streams_service_subset_and_buckets(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("timestamp,msname,cpu_utilization\n0,svc-a,0.4\n30000,svc-a,0.2\n0,svc-b,9.0\n", encoding="utf-8")
    workload = load_alibaba_cpu_subset(path, "svc-a")
    assert workload.timestamps == [0]
    assert abs(workload.demand[0] - 0.6) < 1e-9
    assert "proxy" in workload.signal_name


def test_synthetic_workload_is_repeatable_and_nonnegative():
    a = generate_workload("burst", 40, 5)
    b = generate_workload("burst", 40, 5)
    assert a == b
    assert len(a.demand) == 40
    assert all(value >= 0 for value in a.demand)


def test_periodic_workload_matches_the_preregistered_repeatable_scenario():
    a = generate_workload("periodic", 240, 1000)
    b = generate_workload("periodic", 240, 1000)
    assert a == b
    assert len(a.demand) == 240
    assert all(value >= 0 for value in a.demand)


def test_workload_rejects_invalid_timestamps_and_demand():
    try:
        Workload([0, 1, 1], [1.0, 1.0, 1.0])
        assert False, "non-increasing timestamps should fail"
    except ValueError:
        pass
    try:
        Workload([0], [float("nan")])
        assert False, "non-finite demand should fail"
    except ValueError:
        pass


def test_persistence_forecast_uses_only_supplied_history():
    assert persistence_forecast([1.0, 2.0, 2.5], horizon=3) == 2.5
    assert persistence_forecast([], horizon=2) == 0.0


def test_error_tracker_updates_only_when_caller_observes_matured_forecast():
    tracker = ForecastErrorTracker(window=3)
    assert tracker.mae is None
    tracker.observe(2.0, 3.0)
    assert tracker.mae == 1.0


def test_pending_replicas_provide_no_capacity_until_ready():
    workload = Workload([0, 1, 2, 3], [6.0, 6.0, 6.0, 6.0])
    result = run_experiment(workload, SimulationConfig(initial_replicas=1, readiness_delay_steps=2, forecast_horizon_steps=2))
    reactive = next(p for p in result["policies"] if p["policy"] == "reactive")
    assert reactive["steps"][0]["ready_replicas"] == 1
    assert reactive["steps"][0]["pending_replicas"] > 0
    assert reactive["steps"][0]["capacity"] == 1
    assert reactive["steps"][1]["ready_replicas"] == 1
    assert reactive["steps"][2]["ready_replicas"] > 1


def test_policy_bounds_and_step_limits_are_enforced():
    config = PolicyConfig(min_replicas=1, max_replicas=6, max_scale_up_step=2, max_scale_down_step=1, cooldown_steps=0)
    assert bounded_step(2, 10, config) == 4
    assert bounded_step(2, 0, config) == 1
    target, reasons = hybrid_target(10, 9, 1, 0.5, config)
    assert target <= config.max_replicas
    assert "recent_forecast_error_correction" in reasons


def test_hybrid_correction_ablations_disable_only_the_selected_safety_signal():
    no_current = PolicyConfig(hybrid_current_safety_correction=False)
    target, reasons = hybrid_target(1.0, 8.0, 1, None, no_current)
    assert target == 2
    assert "current_load_safety_correction" not in reasons

    no_error = PolicyConfig(hybrid_forecast_error_correction=False)
    target, reasons = hybrid_target(1.0, 1.0, 1, 0.9, no_error)
    assert target == 2
    assert "recent_forecast_error_correction" not in reasons


def test_metrics_report_capacity_proxy_not_latency_or_money():
    result = run_experiment(generate_workload("stable", 20, 2), SimulationConfig())
    for policy in result["policies"]:
        assert 0 <= policy["metrics"]["capacity_violation_rate"] <= 1
        assert policy["metrics"]["latency_slo_measured"] is False
        assert policy["metrics"]["monetary_cost_measured"] is False


def test_forecast_perturbation_is_reproducible_and_shared_across_policies():
    workload = generate_workload("shift", 24, 9)
    config = SimulationConfig(forecast_bias=-0.2, forecast_noise_std=0.1, forecast_seed=7)
    first = run_experiment(workload, config)
    second = run_experiment(workload, config)
    assert first == second
    forecasts = [p["steps"][5]["forecast"] for p in first["policies"]]
    assert forecasts[0] == forecasts[1] == forecasts[2]


def test_stale_missing_and_breached_signals_prevent_scale_down():
    now = 100.0
    fresh = MetricSample("cpu", 55.0, 98.0, 10.0)
    stale = MetricSample("replicas", 2, 70.0, 10.0)
    missing = MetricSample("memory", None, None, 10.0)
    assert allow_scale_down([fresh], {"cpu"}, now, False)[0]
    assert not allow_scale_down([fresh, stale], {"cpu", "replicas"}, now, False)[0]
    assert not allow_scale_down([fresh, missing], {"cpu", "memory"}, now, False)[0]
    assert not allow_scale_down([fresh], {"cpu"}, now, True)[0]
from backend.app.core.alibaba_trace import load_alibaba_cpu_subset
