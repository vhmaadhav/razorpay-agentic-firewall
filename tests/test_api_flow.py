"""End-to-end integration tests against the real FastAPI app, covering the
4 demo scenarios (12-demo-script.md) plus the adversarial cases that are
architectural rather than pure-policy-engine concerns (35, 42, 46, 47, 50 —
see tests/test_policy_engine.py for where each of the 50 cases lives).
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models import schema  # noqa: F401 (registers tables on Base.metadata)


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_factory)

    from app.main import app

    with TestClient(app) as c:
        c.db_engine = engine  # stashed for tests that need raw DB access (e.g. TOCTOU test)
        yield c


DEMO_MANDATE = {
    "user_id": "user_789",
    "merchant_name": "MerchantA",
    "quantity": 3,
    "category": "chair",
    "allowed_skus": ["CHAIR1"],
    "max_total": 25000,
    "substitutions_allowed": False,
    "expires_in_minutes": 20,
}


def confirm_demo_mandate(client, **overrides):
    mandate = {**DEMO_MANDATE, **overrides}
    resp = client.post("/authorization/confirm", json={"mandate": mandate})
    assert resp.status_code == 200, resp.text
    return resp.json()["authorization_id"]


def demo_cart(**overrides):
    cart = {
        "merchant_id": "MerchantA",
        "items": [{"sku": "CHAIR1", "unit_price": 7500, "quantity": 3, "category": "chair"}],
        "shipping": 1200,
        "tax": 0,
        "total": 23700,
        "currency": "INR",
    }
    cart.update(overrides)
    return cart


def test_scenario_1_allow_full_flow_through_payment_and_evidence(client):
    auth_id = confirm_demo_mandate(client)

    r = client.post(
        "/agent/request",
        json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "ALLOW"
    request_id = body["request_id"]

    r2 = client.post("/payment/execute", json={"authorization_id": auth_id, "request_id": request_id})
    assert r2.status_code == 200
    assert r2.json()["amount"] == 23700

    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"] is True
    event_types = [e["event_type"] for e in evidence["events"]]
    assert event_types == ["MANDATE_SIGNED", "AGENT_REQUEST_RECEIVED", "POLICY_EVALUATED", "ORDER_CREATED"]


def test_scenario_2_reconsent_on_budget_violation(client):
    auth_id = confirm_demo_mandate(client)
    over_budget_cart = demo_cart(
        items=[
            {"sku": "CHAIR1", "unit_price": 7500, "quantity": 3, "category": "chair"},
            {"sku": "WARRANTY", "unit_price": 2500, "quantity": 1, "category": "warranty"},
        ],
        total=26200,  # 3*7500 + 1200 shipping + 2500 warranty
    )

    r = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": over_budget_cart}
    )
    body = r.json()
    # The unauthorized WARRANTY sku is caught before the total is even summed.
    assert body["decision"] in ("RECONSENT", "BLOCK")
    assert body["reason"] in ("MAX_TOTAL_EXCEEDED", "SKU_NOT_ALLOWED")

    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"] == []  # no Razorpay order should ever be created


def test_scenario_2b_pure_budget_violation_without_new_sku_is_reconsent(client):
    auth_id = confirm_demo_mandate(client, allowed_skus=[])
    over_budget_cart = demo_cart(
        items=[{"sku": "CHAIR1", "unit_price": 9000, "quantity": 3, "category": "chair"}],
        total=28200,
    )
    r = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": over_budget_cart}
    )
    body = r.json()
    assert body["decision"] == "RECONSENT"
    assert body["reason"] == "MAX_TOTAL_EXCEEDED"
    assert "2200" in body["message"] or "28200" in body["message"]


def test_scenario_3_block_wrong_merchant(client):
    auth_id = confirm_demo_mandate(client)
    wrong_merchant_cart = demo_cart(
        merchant_id="MerchantB",
        items=[{"sku": "CHAIR1", "unit_price": 7500, "quantity": 2, "category": "chair"}],
        shipping=0, total=15000,
    )

    r = client.post(
        "/agent/request",
        json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": wrong_merchant_cart},
    )
    body = r.json()
    assert body["decision"] == "BLOCK"
    assert body["reason"] == "MERCHANT_NOT_ALLOWED"


def test_scenario_4_replay_attack_is_blocked(client):
    auth_id = confirm_demo_mandate(client)
    payload = {"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()}

    first = client.post("/agent/request", json=payload)
    assert first.json()["decision"] == "ALLOW"

    replay = client.post("/agent/request", json=payload)  # identical request, same nonce
    assert replay.json()["decision"] == "BLOCK"
    assert replay.json()["reason"] == "NONCE_ALREADY_USED"

    tx = client.get(f"/transactions/{auth_id}").json()
    assert len(tx["requests"]) == 1  # the replay did not create a second agent_requests row


def test_case_35_payment_execute_ignores_client_supplied_cart(client):
    """POST /payment/execute's schema (authorization_id, request_id) has no
    cart field at all, so a client cannot smuggle a different cart in between
    the policy check and order creation — the server re-reads its own stored
    agent_requests row (see app/routes/payment.py)."""
    auth_id = confirm_demo_mandate(client)
    r = client.post(
        "/agent/request",
        json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()},
    )
    request_id = r.json()["request_id"]

    tampered = client.post(
        "/payment/execute",
        json={"authorization_id": auth_id, "request_id": request_id, "cart": {"total": 1}},
    )
    assert tampered.status_code == 200
    assert tampered.json()["amount"] == 23700  # unaffected by the extra "cart" field


def test_case_42_webhook_amount_mismatch_is_flagged(client):
    """Simulates a TOCTOU DB tamper: after the order is created, something
    (a compromised process, a bug) rewrites the stored authorized amount
    before the webhook arrives. The webhook handler must detect the mismatch
    rather than silently marking it CAPTURED."""
    from app.models.schema import PaymentExecution

    auth_id = confirm_demo_mandate(client)
    r = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()}
    )
    request_id = r.json()["request_id"]
    order = client.post("/payment/execute", json={"authorization_id": auth_id, "request_id": request_id}).json()

    Session = sessionmaker(bind=client.db_engine)
    session = Session()
    execution = session.query(PaymentExecution).filter_by(razorpay_order_id=order["order_id"]).one()
    execution.amount = 99999  # tamper
    session.commit()
    session.close()

    from app.payment.razorpay_client import MockRazorpayClient, OrderResult

    mock = MockRazorpayClient()
    raw, sig = mock.build_test_webhook(
        OrderResult(order_id=order["order_id"], amount=order["amount"], currency=order["currency"], status="created", receipt=auth_id)
    )
    webhook_resp = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"})
    assert webhook_resp.status_code == 200

    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"][0]["status"] == "AMOUNT_MISMATCH"


def test_case_46_webhook_with_corrupted_signature_is_rejected(client):
    auth_id = confirm_demo_mandate(client)
    r = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()}
    )
    request_id = r.json()["request_id"]
    order = client.post("/payment/execute", json={"authorization_id": auth_id, "request_id": request_id}).json()

    from app.payment.razorpay_client import MockRazorpayClient, OrderResult

    mock = MockRazorpayClient()
    raw, sig = mock.build_test_webhook(
        OrderResult(order_id=order["order_id"], amount=order["amount"], currency=order["currency"], status="created", receipt=auth_id)
    )
    tampered_body = raw.replace(b'"captured"', b'"refunded"')  # body changed after signing

    resp = client.post(
        "/webhooks/razorpay", content=tampered_body, headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    )
    assert resp.status_code == 400


def test_case_47_duplicate_webhook_delivery_is_ignored(client):
    auth_id = confirm_demo_mandate(client)
    r = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz", "cart": demo_cart()}
    )
    request_id = r.json()["request_id"]
    order = client.post("/payment/execute", json={"authorization_id": auth_id, "request_id": request_id}).json()

    from app.payment.razorpay_client import MockRazorpayClient, OrderResult

    mock = MockRazorpayClient()
    raw, sig = mock.build_test_webhook(
        OrderResult(order_id=order["order_id"], amount=order["amount"], currency=order["currency"], status="created", receipt=auth_id)
    )
    headers = {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}

    first = client.post("/webhooks/razorpay", content=raw, headers=headers)
    second = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "duplicate_ignored"


def test_case_50_malformed_agent_request_returns_422(client):
    auth_id = confirm_demo_mandate(client)
    resp = client.post(
        "/agent/request",
        json={"authorization_id": auth_id, "nonce": "n1", "agent_id": "agent_xyz"},  # missing "cart"
    )
    assert resp.status_code == 422
