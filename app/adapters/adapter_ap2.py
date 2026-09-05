"""Adapter A — normalizes an AP2-style open Checkout Mandate into our
CanonicalAuthorizationEnvelope (06-protocol-mapping.md / TASK-004).

This does NOT verify or attach a signature — it only maps fields. Signing
happens afterwards over the freshly-canonicalized envelope (see
app/canonical/hashing.py), because AP2's own JWS is computed over AP2's wire
format, not ours; the trust we inherit is "a key we recognize authorized
these constraints", which the caller re-asserts by signing our canonical form.
"""
from __future__ import annotations

from typing import Any

from app.models.envelope import (
    Agent,
    CanonicalAuthorizationEnvelope,
    ExecutionScope,
    FinancialScope,
    MerchantScope,
    Principal,
    ProductScope,
    QuantityScope,
    TemporalScope,
)


def from_ap2_checkout_mandate(payload: dict[str, Any]) -> CanonicalAuthorizationEnvelope:
    agent_block = payload.get("agent", {})
    return CanonicalAuthorizationEnvelope(
        version=payload.get("vct", "mandate.checkout.open.1"),
        authorization_id=payload["authorization_id"],
        principal=Principal(
            user_id=payload["user_id"],
            identity_provider=payload.get("identity_provider", "ap2"),
        ),
        agent=Agent(
            agent_id=agent_block.get("agent_id", payload.get("agent_id", "unknown")),
            provider=agent_block.get("provider", "ap2-agent"),
            public_key=agent_block.get("public_key", payload.get("agent_public_key", "")),
            trust_level=agent_block.get("trust_level", "user_key"),
        ),
        merchant_scope=MerchantScope(
            merchant_ids=payload.get("merchant_ids", []),
            merchant_categories=payload.get("merchant_categories", []),
        ),
        product_scope=ProductScope(
            allowed_skus=payload.get("allowed_skus", []),
            allowed_categories=payload.get("allowed_categories", []),
            forbidden_skus=payload.get("forbidden_skus", []),
            substitutions_allowed=payload.get("substitutions_allowed", False),
        ),
        financial_scope=FinancialScope(
            currency=payload.get("currency", "INR"),
            max_total=payload["max_total_amount"],
            max_unit_price=payload.get("max_unit_price"),
            shipping_included=payload.get("shipping_included", True),
            tax_included=payload.get("tax_included", True),
            tips_allowed=payload.get("tips_allowed", False),
        ),
        quantity_scope=QuantityScope(max_items=payload.get("max_items", 999)),
        temporal_scope=TemporalScope(
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
        ),
        execution_scope=ExecutionScope(
            max_transactions=payload.get("max_transactions", 1),
            reusable=payload.get("reusable", False),
        ),
        nonce=payload["nonce"],
        evidence_hash="",
        signature=None,
    )
