"""Read-only Kubernetes inspection. This module contains no write operations."""

from __future__ import annotations

import os
from typing import Any



class KubernetesInspectionError(RuntimeError):
    pass


def inspect_deployment_read_only(
    namespace: str,
    deployment_name: str,
    min_replicas: int = 1,
    max_replicas: int = 20,
    target_utilization: float = 0.70,
) -> dict[str, Any]:
    if os.getenv("KUBERNETES_DRY_RUN_ENABLED", "false").lower() != "true":
        raise KubernetesInspectionError("Kubernetes read-only inspection is disabled; set KUBERNETES_DRY_RUN_ENABLED=true explicitly")
    try:
        from kubernetes import client, config

        config.load_kube_config()
        apps = client.AppsV1Api()
        core = client.CoreV1Api()
        custom = client.CustomObjectsApi()
        deployment = apps.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        selector = deployment.spec.selector.match_labels or {}
        if not selector:
            raise KubernetesInspectionError("deployment has no explicit label selector")
        label_selector = ",".join(f"{key}={value}" for key, value in selector.items())
        pods = core.list_namespaced_pod(namespace=namespace, label_selector=label_selector).items
        metrics = custom.list_namespaced_custom_object(
            group="metrics.k8s.io", version="v1beta1", namespace=namespace, plural="pods", label_selector=label_selector
        )
    except KubernetesInspectionError:
        raise
    except Exception as exc:  # Do not include exception details; client errors can contain sensitive endpoint/config context.
        raise KubernetesInspectionError(f"Kubernetes read-only inspection failed ({type(exc).__name__})") from None

    request_cpu_millicores: dict[str, float] = {}
    for pod in pods:
        for container in (pod.spec.containers or []):
            requests = (container.resources.requests or {}) if container.resources else {}
            cpu = requests.get("cpu")
            if cpu:
                request_cpu_millicores[container.name] = _parse_cpu_millicores(cpu)
    usage_by_pod: dict[str, float] = {}
    for pod_metric in metrics.get("items", []):
        total = 0.0
        for container in pod_metric.get("containers", []):
            total += _parse_cpu_millicores(container.get("usage", {}).get("cpu", "0"))
        usage_by_pod[pod_metric.get("metadata", {}).get("name", "")] = total
    pod_cpu_requests = sum(
        request_cpu_millicores.get(c.name, 0.0)
        for pod in pods for c in (pod.spec.containers or [])
    )
    usage = sum(usage_by_pod.values())
    cpu_pct = (usage / pod_cpu_requests * 100.0) if pod_cpu_requests else None
    ready = sum(
        1 for p in pods
        if p.status and any(c.type == "Ready" and c.status == "True" for c in (p.status.conditions or []))
    )
    desired = int(deployment.spec.replicas or 0)
    if min_replicas < 0 or max_replicas < max(1, min_replicas) or not 0 < target_utilization <= 1:
        raise KubernetesInspectionError("invalid recommendation bounds or target utilization")
    target = desired
    reasons = ["no_fresh_cpu_metric"]
    if cpu_pct is not None and ready > 0:
        import math
        target = math.ceil(desired * (cpu_pct / 100.0) / target_utilization)
        target = max(min_replicas, min(max_replicas, target))
        reasons = ["read_only_cpu_ratio_recommendation"]
    return {
        "result_type": "kubernetes_read_only_dry_run",
        "namespace": namespace,
        "deployment": deployment_name,
        "desired_replicas": desired,
        "ready_replicas": ready,
        "cpu_request_millicores": pod_cpu_requests,
        "cpu_usage_millicores": usage,
        "cpu_utilization_percent": cpu_pct,
        "recommended_replicas": target,
        "reasons": reasons,
        "mutated_cluster": False,
        "limitations": ["Forecasting is not connected to the live Kubernetes adapter yet.", "No scaling API was called."],
    }


def _parse_cpu_millicores(value: str) -> float:
    value = str(value).strip()
    if value.endswith("n"):
        return float(value[:-1]) / 1_000_000.0
    if value.endswith("u"):
        return float(value[:-1]) / 1_000.0
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000.0
