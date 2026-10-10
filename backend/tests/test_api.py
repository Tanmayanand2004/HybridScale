from fastapi.testclient import TestClient

from backend.app.api import app


def test_synthetic_run_is_retrievable_and_exportable():
    with TestClient(app) as client:
        response = client.post(
            "/api/experiments/synthetic",
            json={"scenario": "stable", "length": 12, "seed": 912},
        )
        assert response.status_code == 200
        run = response.json()

        detail = client.get(run["detail_url"])
        assert detail.status_code == 200
        assert len(detail.json()["policies"]) == 3

        export = client.get(run["export_url"])
        assert export.status_code == 200
        assert "forecast_target_step" in export.text
        assert "activated_this_step" in export.text

        history = client.get("/api/experiments")
        assert any(item["id"] == run["run_id"] for item in history.json())
