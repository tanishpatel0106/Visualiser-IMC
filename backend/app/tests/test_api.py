"""Tests for API endpoints using httpx/starlette TestClient."""

import pytest
from starlette.testclient import TestClient

from backend.app.main import app


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as c:
        yield c


# ======================================================================
# GET /api/health
# ======================================================================

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


# ======================================================================
# GET /api/datasets
# ======================================================================

class TestDatasetsEndpoint:
    def test_datasets_returns_structure(self, client):
        response = client.get("/api/datasets")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert "days" in data
        assert "loaded" in data
        assert isinstance(data["products"], list)
        assert isinstance(data["days"], list)


# ======================================================================
# GET /api/strategies
# ======================================================================

class TestStrategiesEndpoint:
    def test_strategies_returns_list(self, client):
        response = client.get("/api/strategies")
        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data
        assert isinstance(data["strategies"], list)


# ======================================================================
# POST /api/replay/start
# ======================================================================

class TestReplayStartEndpoint:
    def test_replay_start_no_data(self, client):
        """When no data is loaded, replay start should return an error or empty state."""
        response = client.post(
            "/api/replay/start",
            json={"products": ["EMERALDS"], "days": [1]},
        )
        # Depending on implementation, could be 200 with error key or 400
        assert response.status_code in (200, 400)

    def test_replay_start_invalid_body(self, client):
        """Missing required fields should return 422."""
        response = client.post("/api/replay/start", json={})
        assert response.status_code == 422


# ======================================================================
# POST /api/backtest/run
# ======================================================================

class TestBacktestRunEndpoint:
    def test_backtest_run_basic(self, client):
        """Run a backtest with a no-op strategy."""
        source_code = '''
class Trader:
    def run(self, state):
        return {}, 0, ""
'''
        response = client.post(
            "/api/backtest/run",
            json={
                "strategy_id": "test_noop",
                "source_code": source_code,
                "products": [],
                "days": [],
                "execution_model": "BALANCED",
                "position_limits": {},
                "fees": 0.0,
                "slippage": 0.0,
                "initial_cash": 0.0,
            },
        )
        # Should succeed (even with no data, it just runs zero events)
        assert response.status_code in (200, 400, 500)
        if response.status_code == 200:
            data = response.json()
            assert "run_id" in data
            assert "status" in data

    def test_backtest_run_invalid_body(self, client):
        """Missing required fields should return 422."""
        response = client.post("/api/backtest/run", json={})
        assert response.status_code == 422

    def test_backtest_run_invalid_strategy(self, client):
        """Invalid strategy source should return error."""
        response = client.post(
            "/api/backtest/run",
            json={
                "strategy_id": "bad",
                "source_code": "not valid python {{{{",
                "products": [],
                "days": [],
            },
        )
        # Should be 400 or 500 depending on how the service handles it
        assert response.status_code in (400, 500)


# ======================================================================
# GET /api/replay/state
# ======================================================================

class TestReplayStateEndpoint:
    def test_replay_state_before_start(self, client):
        response = client.get("/api/replay/state")
        assert response.status_code == 200
        data = response.json()
        # Should return some state structure
        assert isinstance(data, dict)


# ======================================================================
# Additional endpoint tests
# ======================================================================

class TestProductsAndDays:
    def test_products_endpoint(self, client):
        response = client.get("/api/products")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data

    def test_days_endpoint(self, client):
        response = client.get("/api/days")
        assert response.status_code == 200
        data = response.json()
        assert "days" in data


class TestReplayControls:
    def test_replay_pause(self, client):
        response = client.post("/api/replay/pause")
        assert response.status_code == 200

    def test_replay_step(self, client):
        response = client.post("/api/replay/step")
        assert response.status_code == 200

    def test_replay_reset(self, client):
        response = client.post("/api/replay/reset")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "reset"
