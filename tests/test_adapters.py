from app.adapters.adapter_ap2 import from_ap2_checkout_mandate
from app.adapters.adapter_generic import from_generic_delegation


def test_ap2_adapter_maps_fields_correctly():
    payload = {
        "vct": "mandate.checkout.open.1",
        "authorization_id": "auth-ap2-1",
        "user_id": "user_789",
        "agent": {"agent_id": "agent_xyz", "provider": "MyAssistant", "public_key": "pk123", "trust_level": "user_key"},
        "merchant_ids": ["MerchantA"],
        "allowed_skus": ["CHAIR1"],
        "allowed_categories": ["chair"],
        "max_total_amount": 25000,
        "currency": "INR",
        "max_items": 3,
        "issued_at": "2026-09-05T18:00:00Z",
        "expires_at": "2026-09-05T18:20:00Z",
        "nonce": "abc123xyz",
    }

    envelope = from_ap2_checkout_mandate(payload)

    assert envelope.authorization_id == "auth-ap2-1"
    assert envelope.agent.agent_id == "agent_xyz"
    assert envelope.agent.public_key == "pk123"
    assert envelope.merchant_scope.merchant_ids == ["MerchantA"]
    assert envelope.product_scope.allowed_skus == ["CHAIR1"]
    assert envelope.financial_scope.max_total == 25000
    assert envelope.quantity_scope.max_items == 3
    assert envelope.nonce == "abc123xyz"
    assert envelope.evidence_hash == ""  # unsigned until the confirm step signs it


def test_ap2_adapter_defaults_unrestricted_scopes_when_absent():
    payload = {
        "authorization_id": "auth-ap2-2",
        "user_id": "user_789",
        "max_total_amount": 5000,
        "issued_at": "2026-09-05T18:00:00Z",
        "expires_at": "2026-09-05T18:20:00Z",
        "nonce": "n2",
    }

    envelope = from_ap2_checkout_mandate(payload)

    assert envelope.merchant_scope.merchant_ids == []
    assert envelope.product_scope.allowed_skus == []
    assert envelope.quantity_scope.max_items == 999


def test_generic_adapter_maps_fields_correctly():
    payload = {
        "authorization_id": "auth-gen-1",
        "user_id": "user_789",
        "agent_id": "agent_456",
        "agent_public_key": "pk456",
        "max_amount": 50000,
        "merchant_ids": ["MerchantX"],
        "issued_at": "2026-09-05T18:00:00Z",
        "expires_at": "2026-09-06T18:00:00Z",
        "nonce": "generic-nonce-1",
    }

    envelope = from_generic_delegation(payload)

    assert envelope.authorization_id == "auth-gen-1"
    assert envelope.agent.agent_id == "agent_456"
    assert envelope.financial_scope.max_total == 50000
    assert envelope.merchant_scope.merchant_ids == ["MerchantX"]
    assert envelope.nonce == "generic-nonce-1"
