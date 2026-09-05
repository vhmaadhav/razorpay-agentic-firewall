"""Case 49: revocation at ingestion and between ALLOW and payment execution."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.models.schema import Authorization, MandateRevocation
from app.payment.razorpay_client import MockRazorpayClient, OrderResult
from tests.test_api_flow import client, confirm_demo_mandate, demo_cart, post_signed


def submit(client, auth_id, nonce="n1"):
    return post_signed(client, "/agent/request", json={
        "authorization_id": auth_id, "agent_id": "agent_xyz", "nonce": nonce, "cart": demo_cart(),
    })


def revoke(client, auth_id, reason="compromised agent"):
    return client.post(f"/authorization/{auth_id}/revoke", json={"reason": reason})


def test_case_49_revoke_before_agent_request_blocks_valid_signature(client):
    auth_id = confirm_demo_mandate(client)
    before = client.get(f"/transactions/{auth_id}").json()
    assert before["status"] == "SIGNED" and before["revocation"] is None
    response = revoke(client, auth_id)
    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"
    result = submit(client, auth_id).json()
    assert result["decision"] == "BLOCK" and result["reason"] == "MANDATE_REVOKED"
    after = client.get(f"/transactions/{auth_id}").json()
    assert after["status"] == "REVOKED"
    assert after["revocation"]["reason"] == "compromised agent"
    assert after["mandate"] == before["mandate"]  # signed bytes are unchanged
    assert after["used_count"] == 0 and after["payments"] == []
    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert [e["event_type"] for e in evidence["events"]] == [
        "MANDATE_SIGNED", "MANDATE_REVOKED", "AGENT_REQUEST_RECEIVED", "POLICY_EVALUATED",
    ]
    assert evidence["events"][1]["actor"] == "trusted-operator"


def test_case_49_revoke_after_allow_never_calls_payment_provider(client, monkeypatch):
    auth_id = confirm_demo_mandate(client)
    result = submit(client, auth_id).json()
    assert result["decision"] == "ALLOW"
    assert revoke(client, auth_id).status_code == 200

    def forbidden_executor():
        pytest.fail("Revoked mandate reached payment provider")

    monkeypatch.setattr("app.routes.payment.get_payment_executor", forbidden_executor)
    response = client.post("/payment/execute", json={
        "authorization_id": auth_id, "request_id": result["request_id"],
    })
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "MANDATE_REVOKED"
    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"] == []
    assert tx["decisions"][0]["decision"] == "ALLOW"  # historical result preserved


def test_revocation_is_idempotent_with_one_immutable_event(client):
    auth_id = confirm_demo_mandate(client)
    first = revoke(client, auth_id).json()
    second = revoke(client, auth_id, "changed reason").json()
    assert first == second
    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert len([e for e in evidence["events"] if e["event_type"] == "MANDATE_REVOKED"]) == 1


def test_revoking_one_mandate_does_not_revoke_another(client):
    first = confirm_demo_mandate(client)
    second = confirm_demo_mandate(client)
    revoke(client, first)
    assert submit(client, second).json()["decision"] == "ALLOW"


def test_unknown_revocation_is_404(client):
    assert revoke(client, "unknown").status_code == 404


@pytest.mark.parametrize("reason", ["", "  ", "x" * 501, None])
def test_invalid_reason_is_422(client, reason):
    auth_id = confirm_demo_mandate(client)
    assert revoke(client, auth_id, reason).status_code == 422
    assert client.get(f"/transactions/{auth_id}").json()["status"] == "SIGNED"


def test_empty_object_uses_default_reason(client):
    auth_id = confirm_demo_mandate(client)
    result = client.post(f"/authorization/{auth_id}/revoke", json={}).json()
    assert result["reason"] == "operator_request"


def test_created_order_is_preserved_and_late_webhook_is_recorded(client):
    auth_id = confirm_demo_mandate(client)
    result = submit(client, auth_id).json()
    payment_payload = {"authorization_id": auth_id, "request_id": result["request_id"]}
    order = client.post("/payment/execute", json=payment_payload).json()
    revoke(client, auth_id)
    assert client.post("/payment/execute", json=payment_payload).status_code == 409
    raw, signature = MockRazorpayClient().build_test_webhook(
        OrderResult(order["order_id"], order["amount"], order["currency"], "created", auth_id),
    )
    response = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": signature})
    assert response.status_code == 200
    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["status"] == "REVOKED"
    assert len(tx["payments"]) == 1 and tx["payments"][0]["status"] == "CAPTURED"
    assert client.get(f"/transactions/{auth_id}/evidence").json()["chain_valid"]


def test_revocation_and_evidence_rollback_together(client, monkeypatch):
    from app.routes.authorization import revoke_authorization, RevokeRequest

    def fail_append(*args, **kwargs):
        raise RuntimeError("evidence write failed")

    auth_id = confirm_demo_mandate(client)
    monkeypatch.setattr("app.routes.authorization.append_event", fail_append)
    with db_module.SessionLocal() as db:
        with pytest.raises(RuntimeError, match="evidence write failed"):
            revoke_authorization(auth_id, RevokeRequest(), db)
        db.rollback()
    assert client.get(f"/transactions/{auth_id}").json()["status"] == "SIGNED"


@pytest.fixture()
def file_client(monkeypatch, tmp_path):
    # Separate connections are required to exercise real SQLite locking.
    engine = create_engine(f"sqlite:///{(tmp_path / 'revocation.db').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False))
    from app.main import app
    with TestClient(app) as c:
        yield c
    engine.dispose()


def test_concurrent_revokes_commit_one_event(file_client):
    auth_id = confirm_demo_mandate(file_client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(revoke, file_client, auth_id) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert all(r.status_code == 200 for r in results)
    assert results[0].json() == results[1].json()
    events = file_client.get(f"/transactions/{auth_id}/evidence").json()
    assert events["chain_valid"] and len(events["events"]) == 2


def test_revocation_waits_for_already_started_order(file_client, monkeypatch):
    entered, release, revoke_started = Event(), Event(), Event()

    class PausedExecutor(MockRazorpayClient):
        def create_order(self, **kwargs):
            entered.set()
            assert release.wait(5), "Test did not release provider"
            return super().create_order(**kwargs)

    monkeypatch.setattr("app.routes.payment.get_payment_executor", PausedExecutor)
    auth_id = confirm_demo_mandate(file_client)
    result = submit(file_client, auth_id).json()
    payload = {"authorization_id": auth_id, "request_id": result["request_id"]}

    def start_revoke():
        revoke_started.set()
        return revoke(file_client, auth_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        payment = pool.submit(file_client.post, "/payment/execute", json=payload)
        try:
            assert entered.wait(5)
            revocation = pool.submit(start_revoke)
            assert revoke_started.wait(5)
            # Revocation must not report success while a locked provider call
            # is still in flight. A missing shared lock fails this assertion.
            from concurrent.futures import TimeoutError
            with pytest.raises(TimeoutError):
                revocation.result(timeout=0.15)
        finally:
            release.set()
        assert payment.result(timeout=5).status_code == 200
        assert revocation.result(timeout=5).status_code == 200
    assert file_client.post("/payment/execute", json=payload).status_code == 409
    assert len(file_client.get(f"/transactions/{auth_id}").json()["payments"]) == 1
    assert file_client.get(f"/transactions/{auth_id}/evidence").json()["chain_valid"]


def test_revocation_wins_before_payment_provider_is_entered(file_client, monkeypatch):
    from app.routes import authorization
    from concurrent.futures import TimeoutError

    entered, release, payment_started = Event(), Event(), Event()
    original_append = authorization.append_event

    def paused_append(*args, **kwargs):
        if kwargs["event_type"] == "MANDATE_REVOKED":
            entered.set()
            assert release.wait(5)
        return original_append(*args, **kwargs)

    def forbidden_executor():
        pytest.fail("Payment provider called after revocation won the lock")

    auth_id = confirm_demo_mandate(file_client)
    result = submit(file_client, auth_id).json()
    monkeypatch.setattr(authorization, "append_event", paused_append)
    monkeypatch.setattr("app.routes.payment.get_payment_executor", forbidden_executor)

    def pay():
        payment_started.set()
        return file_client.post("/payment/execute", json={
            "authorization_id": auth_id, "request_id": result["request_id"],
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        revocation = pool.submit(revoke, file_client, auth_id)
        try:
            assert entered.wait(5)
            payment = pool.submit(pay)
            assert payment_started.wait(5)
            with pytest.raises(TimeoutError):
                payment.result(timeout=0.15)
        finally:
            release.set()
        assert revocation.result(timeout=5).status_code == 200
        response = payment.result(timeout=5)
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "MANDATE_REVOKED"
    assert file_client.get(f"/transactions/{auth_id}").json()["payments"] == []
    assert file_client.get(f"/transactions/{auth_id}/evidence").json()["chain_valid"]


def test_revocation_survives_a_new_database_connection(file_client):
    auth_id = confirm_demo_mandate(file_client)
    revoke(file_client, auth_id)
    db_module.engine.dispose()
    assert submit(file_client, auth_id).json()["reason"] == "MANDATE_REVOKED"


def test_additive_schema_upgrade_preserves_existing_mandates(client):
    auth_id = confirm_demo_mandate(client)
    # Simulate the pre-revocation schema in this isolated in-memory fixture.
    MandateRevocation.__table__.drop(db_module.engine)
    db_module.init_db()
    with db_module.SessionLocal() as db:
        assert db.get(Authorization, auth_id) is not None
    assert revoke(client, auth_id).status_code == 200
