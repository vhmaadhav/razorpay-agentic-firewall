"""Adapter B — normalizes a generic signed-delegation JSON (catch-all for
proprietary agent-platform JWS payloads, per 06-protocol-mapping.md) into the
CanonicalAuthorizationEnvelope. Expected shape:

{"user_id":..., "agent_id":..., "agent_public_key":..., "max_amount":...,
 "merchant_ids":[...], "issued_at":..., "expires_at":..., "nonce":...}

Any field the source format doesn't carry (SKU lists, quantity caps, etc.)
defaults to "no restriction", matching 06-protocol-mapping.md's mapping rule.
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


def from_generic_delegation(payload: dict[str, Any]) -> CanonicalAuthorizationEnvelope:
    return CanonicalAuthorizationEnvelope(
        version="1.0",
        authorization_id=payload["authorization_id"],
        principal=Principal(user_id=payload["user_id"], identity_provider=payload.get("identity_provider", "generic")),
        agent=Agent(
            agent_id=payload["agent_id"],
            provider=payload.get("agent_provider", "generic-agent"),
            public_key=payload.get("agent_public_key", ""),
            trust_level=payload.get("trust_level", "platform_key"),
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
            max_total=payload["max_amount"],
            max_unit_price=payload.get("max_unit_price"),
            shipping_included=payload.get("shipping_included", True),
            tax_included=payload.get("tax_included", True),
            tips_allowed=payload.get("tips_allowed", False),
        ),
        quantity_scope=QuantityScope(max_items=payload.get("max_items", 999)),
        temporal_scope=TemporalScope(issued_at=payload["issued_at"], expires_at=payload["expires_at"]),
        execution_scope=ExecutionScope(
            max_transactions=payload.get("max_transactions", 1),
            reusable=payload.get("reusable", False),
        ),
        nonce=payload["nonce"],
        evidence_hash="",
        signature=None,
    )
