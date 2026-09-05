from concurrent.futures import ThreadPoolExecutor

import pytest

from app.rate_limit import AgentRequestLimiter
from tests.test_api_flow import client, confirm_demo_mandate, demo_cart, post_signed


def limiter(**overrides):
    options = dict(per_client=2, global_limit=10, window_seconds=60, max_clients=4,
                   clock=lambda: 100.0)
    return AgentRequestLimiter(**(options | overrides))


def test_client_boundary_and_expiration_without_sleeping():
    now = [100.0]
    gate = limiter(clock=lambda: now[0])
    assert gate.admit("a") is None
    assert gate.admit("a") is None
    assert gate.admit("a") == 60
    now[0] = 159.2
    assert gate.admit("a") == 1
    now[0] = 160.0
    assert gate.admit("a") is None


def test_clients_have_separate_limits_but_share_global_ceiling():
    gate = limiter(global_limit=3)
    assert gate.admit("a") is None
    assert gate.admit("a") is None
    assert gate.admit("b") is None
    assert gate.admit("c") == 60


def test_new_client_flood_cannot_evict_an_active_quota():
    now = [100.0]
    gate = limiter(max_clients=1, clock=lambda: now[0])
    assert gate.admit("a") is None
    assert gate.admit("b") == 60
    assert gate.admit("a") is None
    assert gate.admit("a") == 60
    assert len(gate._clients) == 1
    now[0] += 60
    assert gate.admit("b") is None
    assert list(gate._clients) == ["b"]


def test_concurrent_burst_cannot_exceed_quota():
    gate = limiter(per_client=10, global_limit=100)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(gate.admit, ["same-client"] * 80))
    assert results.count(None) == 10
    assert results.count(60) == 70


@pytest.mark.parametrize("field", ["per_client", "global_limit", "window_seconds", "max_clients"])
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_configuration_fails_closed(field, value):
    with pytest.raises(ValueError, match="must be positive"):
        limiter(**{field: value})


def test_429_precedes_json_parsing_and_database_access(client, monkeypatch):
    from app.db import get_db
    from app.main import app
    app.state.agent_request_limiter = limiter(per_client=1)
    assert client.post("/agent/request", content="invalid json").status_code == 422

    def forbidden_db():
        pytest.fail("Rate-limited request reached database dependency")
        yield

    app.dependency_overrides[get_db] = forbidden_db
    try:
        response = client.post("/agent/request", content="still invalid")
    finally:
        app.dependency_overrides.pop(get_db)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["detail"]["reason"] == "RATE_LIMIT_EXCEEDED"


def test_headers_and_claimed_agent_ids_do_not_reset_quota(client):
    from app.main import app
    app.state.agent_request_limiter = limiter(per_client=1)
    assert client.post("/agent/request", json={"agent_id": "one"}).status_code == 422
    response = client.post("/agent/request", json={"agent_id": "two"}, headers={
        "X-Forwarded-For": "198.51.100.9", "X-Real-IP": "198.51.100.10",
    })
    assert response.status_code == 429
    assert client.get("/health").status_code == 200
    assert client.post("/intent/compile", json={"intent_text": "Buy 3 chairs"}).status_code == 200


def test_denied_signed_request_does_not_consume_nonce_and_recovers(client):
    from app.main import app
    now = [100.0]
    app.state.agent_request_limiter = limiter(per_client=1, clock=lambda: now[0])
    auth_id = confirm_demo_mandate(client)
    # Malformed attempts count too, then a valid signed request is throttled.
    assert client.post("/agent/request", json={}).status_code == 422
    payload = {"authorization_id": auth_id, "nonce": "fresh", "agent_id": "agent_xyz", "cart": demo_cart()}
    assert post_signed(client, "/agent/request", json=payload).status_code == 429
    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["used_count"] == 0 and tx["requests"] == tx["decisions"] == tx["payments"] == []
    assert len(client.get(f"/transactions/{auth_id}/evidence").json()["events"]) == 1
    now[0] += 60
    result = post_signed(client, "/agent/request", json=payload)
    assert result.status_code == 200 and result.json()["decision"] == "ALLOW"


def test_trailing_slash_cannot_bypass_limit(client):
    from app.main import app
    app.state.agent_request_limiter = limiter(per_client=1)
    assert client.post("/agent/request", json={}).status_code == 422
    assert client.post("/agent/request/", json={}, follow_redirects=False).status_code == 429


@pytest.mark.parametrize("path,root", [("/agent/request", ""), ("/api/agent/request", "/api")])
def test_throttling_does_not_read_request_body(path, root):
    import asyncio
    from types import SimpleNamespace
    from app.rate_limit import AgentRateLimitMiddleware

    gate = limiter(per_client=1)
    gate.admit("127.0.0.1")
    messages = []

    async def forbidden_receive():
        pytest.fail("Throttled request body was read")

    async def forbidden_app(*args):
        pytest.fail("Throttled request reached route handler")

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "method": "POST", "path": path, "root_path": root,
        "client": ("127.0.0.1", 5000),
        "app": SimpleNamespace(state=SimpleNamespace(agent_request_limiter=gate)),
    }
    asyncio.run(AgentRateLimitMiddleware(forbidden_app)(scope, forbidden_receive, send))
    assert messages[0]["status"] == 429


def test_global_limit_is_atomic_across_concurrent_clients():
    gate = limiter(per_client=10, global_limit=10, max_clients=100)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(gate.admit, [str(i) for i in range(80)]))
    assert results.count(None) == 10


def test_invalid_settings_prevent_application_startup(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "agent_rate_limit", 0)
    with pytest.raises(ValueError, match="must be positive"):
        with TestClient(app):
            pass
