"""Case 27: exercise the real ingestion route with attacker-controlled input."""
from copy import deepcopy

import pytest

from app.crypto.agent_request import sign_request
from app.crypto.signature import generate_keypair
from tests.test_api_flow import (
    client, confirm_demo_mandate, demo_cart, AGENT_PRIVATE_KEY,
)


def signed_payload(auth_id):
    return sign_request({
        "authorization_id": auth_id, "agent_id": "agent_xyz", "nonce": "signed-nonce",
        "cart": demo_cart(),
    }, AGENT_PRIVATE_KEY)


@pytest.mark.parametrize("signature", [None, "", "%%%", "AAAA", "é", "A" * 88])
def test_case_27_invalid_agent_request_signature_blocks(client, signature):
    auth_id = confirm_demo_mandate(client)
    payload = signed_payload(auth_id)
    payload["agent_signature"] = signature
    response = client.post("/agent/request", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "AGENT_SIGNATURE_INVALID"
    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["requests"] == tx["decisions"] == tx["payments"] == []
    assert tx["used_count"] == 0
    # Rejection must not consume the nonce or prevent the legitimate request.
    assert client.post("/agent/request", json=signed_payload(auth_id)).json()["decision"] == "ALLOW"
    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert evidence["events"][1]["event_type"] == "AGENT_REQUEST_REJECTED"


@pytest.mark.parametrize("field,value", [
    ("merchant_id", "attacker"), ("shipping", 1201), ("tax", 1),
    ("total", 23701), ("currency", "USD"),
])
def test_every_cart_field_is_bound(client, field, value):
    payload = signed_payload(confirm_demo_mandate(client))
    payload["cart"][field] = value
    assert client.post("/agent/request", json=payload).status_code == 401


@pytest.mark.parametrize("field,value", [
    ("sku", "OTHER"), ("quantity", 2), ("unit_price", 1), ("category", "other"),
])
def test_every_line_item_field_is_bound(client, field, value):
    payload = signed_payload(confirm_demo_mandate(client))
    payload["cart"]["items"][0][field] = value
    assert client.post("/agent/request", json=payload).status_code == 401


@pytest.mark.parametrize("field", ["nonce", "agent_id", "authorization_id"])
def test_request_identity_and_nonce_are_bound(client, field):
    payload = signed_payload(confirm_demo_mandate(client))
    payload[field] = confirm_demo_mandate(client) if field == "authorization_id" else "different"
    assert client.post("/agent/request", json=payload).status_code == 401


def test_attacker_key_and_mandate_signature_cannot_sign_requests(client):
    auth_id = confirm_demo_mandate(client)
    payload = signed_payload(auth_id)
    attacker_key, _ = generate_keypair()
    forged = sign_request(payload, attacker_key)
    assert client.post("/agent/request", json=forged).status_code == 401
    payload["agent_signature"] = client.get(f"/transactions/{auth_id}").json()["mandate"]["signature"]
    assert client.post("/agent/request", json=payload).status_code == 401


def test_valid_signed_replay_remains_blocked_and_forgery_does_not_override_allow(client):
    auth_id = confirm_demo_mandate(client)
    payload = signed_payload(auth_id)
    first = client.post("/agent/request", json=payload).json()
    assert first["decision"] == "ALLOW"
    forged = {**payload, "agent_signature": "invalid"}
    assert client.post("/agent/request", json=forged).status_code == 401
    tx = client.get(f"/transactions/{auth_id}").json()
    assert len(tx["decisions"]) == 1 and tx["decisions"][0]["decision"] == "ALLOW"
    replay = client.post("/agent/request", json=payload).json()
    assert replay["decision"] == "BLOCK" and replay["reason"] == "NONCE_ALREADY_USED"


@pytest.mark.parametrize("key", ["bad", "é", "", "AAAA"])
def test_invalid_enrollment_keys_return_422(client, key):
    response = client.post("/authorization/confirm", json={"mandate": {"max_total": 25000}, "agent_public_key": key})
    assert response.status_code == 422


def test_agent_key_is_covered_by_mandate_signature(client):
    from sqlalchemy.orm import Session
    from app.models.schema import Authorization
    auth_id = confirm_demo_mandate(client)
    attacker_key, attacker_public = generate_keypair()
    with Session(client.db_engine) as db:
        row = db.get(Authorization, auth_id)
        envelope = deepcopy(row.envelope)
        envelope["agent"]["request_public_key"] = attacker_public
        row.envelope = envelope
        db.commit()
    payload = sign_request(signed_payload(auth_id), attacker_key)
    response = client.post("/agent/request", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "SIGNATURE_INVALID"
