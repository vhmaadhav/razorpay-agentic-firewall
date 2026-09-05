"""Shared fixture factories for policy-engine tests.

Defaults describe the canonical demo mandate from 12-demo-script.md
Scenario 1: 3 chairs, max ₹25,000, Merchant A only, no substitutions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.envelope import (
    Agent,
    CanonicalAuthorizationEnvelope,
    Cart,
    CartItem,
    ExecutionScope,
    FinancialScope,
    MerchantScope,
    Principal,
    ProductScope,
    QuantityScope,
    TemporalScope,
)

NOW = datetime(2026, 9, 5, 18, 10, 0, tzinfo=timezone.utc)


def make_auth(**overrides: Any) -> CanonicalAuthorizationEnvelope:
    defaults: dict[str, Any] = dict(
        version="1.0",
        authorization_id="auth-12345",
        principal=Principal(user_id="user_789", identity_provider="razorpay"),
        agent=Agent(agent_id="agent_xyz", provider="MyAssistant", public_key="test-key", trust_level="user_key"),
        merchant_scope=MerchantScope(merchant_ids=["MerchantA"], merchant_categories=[]),
        product_scope=ProductScope(
            allowed_skus=["CHAIR1"], allowed_categories=["chair"], forbidden_skus=[], substitutions_allowed=False
        ),
        financial_scope=FinancialScope(
            currency="INR", max_total=25000, max_unit_price=None,
            shipping_included=True, tax_included=True, tips_allowed=False,
        ),
        quantity_scope=QuantityScope(max_items=3),
        temporal_scope=TemporalScope(
            issued_at=(NOW - timedelta(minutes=1)).isoformat(),
            expires_at=(NOW + timedelta(minutes=20)).isoformat(),
        ),
        execution_scope=ExecutionScope(max_transactions=1, reusable=False),
        nonce="nonce-1",
        evidence_hash="test-hash",
        signature="test-signature",
    )
    defaults.update(overrides)
    return CanonicalAuthorizationEnvelope(**defaults)


def make_cart(**overrides: Any) -> Cart:
    items = overrides.pop("items", None)
    if items is None:
        items = [CartItem(sku="CHAIR1", unit_price=7500, quantity=3, category="chair")]
    defaults: dict[str, Any] = dict(
        merchant_id="MerchantA", items=items, shipping=1200, tax=0, total=23700, currency="INR"
    )
    defaults.update(overrides)
    return Cart(**defaults)


def eval_default(auth=None, cart=None, **kwargs):
    from app.policy.engine import evaluate_policy

    return evaluate_policy(
        auth or make_auth(), cart or make_cart(),
        current_time=kwargs.pop("current_time", NOW),
        skip_signature_check=kwargs.pop("skip_signature_check", True),
        **kwargs,
    )
