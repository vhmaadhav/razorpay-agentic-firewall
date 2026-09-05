"""Deterministic policy engine — 04-policy-engine.md.

No LLM/AI is in this call path. `evaluate_policy` is a pure function: same
inputs always produce the same (decision, reason, message) — this is what
makes the firewall auditable. All stateful lookups (nonce-seen, transactions
already used) are resolved by the caller and passed in, so this module has
zero I/O and is trivially unit-testable (see tests/test_policy_engine.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import NamedTuple

from app.crypto import signature as crypto_signature
from app.models.envelope import CanonicalAuthorizationEnvelope, Cart


class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    RECONSENT = "RECONSENT"


class Reason(str, Enum):
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    NOT_YET_VALID = "NOT_YET_VALID"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    MERCHANT_NOT_ALLOWED = "MERCHANT_NOT_ALLOWED"
    MANDATE_EXHAUSTED = "MANDATE_EXHAUSTED"
    NONCE_ALREADY_USED = "NONCE_ALREADY_USED"
    MALFORMED_CART = "MALFORMED_CART"
    ZERO_BUDGET = "ZERO_BUDGET"
    SKU_FORBIDDEN = "SKU_FORBIDDEN"
    SKU_NOT_ALLOWED = "SKU_NOT_ALLOWED"
    SUBSTITUTION_NOT_ALLOWED = "SUBSTITUTION_NOT_ALLOWED"
    QUANTITY_EXCEEDED = "QUANTITY_EXCEEDED"
    UNIT_PRICE_EXCEEDED = "UNIT_PRICE_EXCEEDED"
    TIPS_NOT_ALLOWED = "TIPS_NOT_ALLOWED"
    MAX_TOTAL_EXCEEDED = "MAX_TOTAL_EXCEEDED"
    NONE = ""


class PolicyResult(NamedTuple):
    decision: Decision
    reason: Reason
    message: str


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_policy(
    auth: CanonicalAuthorizationEnvelope,
    cart: Cart,
    *,
    current_time: datetime | None = None,
    nonce_already_used: bool = False,
    transactions_used: int = 0,
    verification_public_key: str | None = None,
    skip_signature_check: bool = False,
) -> PolicyResult:
    now = current_time or datetime.now(timezone.utc)

    # 1. Signature: the mandate must be signed and untampered.
    if not skip_signature_check:
        pub_key = verification_public_key or auth.agent.public_key
        if not auth.signature or not crypto_signature.verify(auth.evidence_hash, auth.signature, pub_key):
            return PolicyResult(Decision.BLOCK, Reason.SIGNATURE_INVALID, "Mandate signature is missing or invalid.")

    # 2. Temporal validity.
    expires_at = _parse_iso(auth.temporal_scope.expires_at)
    issued_at = _parse_iso(auth.temporal_scope.issued_at)
    if now > expires_at:
        return PolicyResult(Decision.BLOCK, Reason.MANDATE_EXPIRED, "Mandate has expired.")
    if now < issued_at:
        return PolicyResult(Decision.BLOCK, Reason.NOT_YET_VALID, "Mandate is not yet valid.")

    # 3. Currency.
    if cart.currency != auth.financial_scope.currency:
        return PolicyResult(
            Decision.BLOCK, Reason.CURRENCY_MISMATCH,
            f"Cart currency {cart.currency} != mandate currency {auth.financial_scope.currency}.",
        )

    # 4. Merchant scope (empty list == any merchant allowed).
    allowed_merchants = auth.merchant_scope.merchant_ids
    if allowed_merchants and cart.merchant_id not in allowed_merchants:
        return PolicyResult(
            Decision.BLOCK, Reason.MERCHANT_NOT_ALLOWED,
            f"Merchant '{cart.merchant_id}' is not in the authorized merchant list.",
        )

    # 5. Execution scope: mandate reuse budget.
    if auth.execution_scope.max_transactions <= 0:
        return PolicyResult(Decision.BLOCK, Reason.MANDATE_EXHAUSTED, "Mandate allows zero transactions.")
    if transactions_used >= auth.execution_scope.max_transactions:
        return PolicyResult(Decision.BLOCK, Reason.MANDATE_EXHAUSTED, "Mandate has no remaining uses.")

    # 6. Replay protection.
    if nonce_already_used:
        return PolicyResult(Decision.BLOCK, Reason.NONCE_ALREADY_USED, "This nonce has already been consumed.")

    # 7. Cart well-formedness (defend against malformed/negative-value carts).
    if cart.total is None or cart.total < 0 or cart.shipping < 0 or cart.tax < 0:
        return PolicyResult(Decision.BLOCK, Reason.MALFORMED_CART, "Cart total/shipping/tax missing or negative.")
    for item in cart.items:
        if item.unit_price < 0 or item.quantity < 0:
            return PolicyResult(Decision.BLOCK, Reason.MALFORMED_CART, f"Item {item.sku} has a negative price/quantity.")

    computed_total = sum(item.unit_price * item.quantity for item in cart.items) + cart.shipping + cart.tax
    if computed_total != cart.total:
        return PolicyResult(
            Decision.BLOCK, Reason.MALFORMED_CART,
            f"Declared total {cart.total} does not match computed total {computed_total}.",
        )

    # 8. Zero-budget mandate.
    if auth.financial_scope.max_total == 0 and cart.total > 0:
        return PolicyResult(Decision.BLOCK, Reason.ZERO_BUDGET, "Mandate authorizes zero spend.")

    # 9. Per-item product scope checks.
    forbidden = set(auth.product_scope.forbidden_skus)
    allowed_skus = set(auth.product_scope.allowed_skus)
    allowed_categories = set(auth.product_scope.allowed_categories)
    total_quantity = 0
    for item in cart.items:
        total_quantity += item.quantity

        if item.sku in forbidden:
            return PolicyResult(Decision.BLOCK, Reason.SKU_FORBIDDEN, f"SKU '{item.sku}' is explicitly forbidden.")

        sku_ok = (not allowed_skus) or item.sku in allowed_skus
        category_ok = (not allowed_categories) or (item.category in allowed_categories)

        if allowed_skus and item.sku not in allowed_skus:
            if auth.product_scope.substitutions_allowed and category_ok:
                pass  # substitution within an allowed category is fine
            elif auth.product_scope.substitutions_allowed:
                return PolicyResult(
                    Decision.BLOCK, Reason.SUBSTITUTION_NOT_ALLOWED,
                    f"Substituted SKU '{item.sku}' is outside the authorized categories.",
                )
            else:
                return PolicyResult(Decision.BLOCK, Reason.SKU_NOT_ALLOWED, f"SKU '{item.sku}' is not authorized.")
        elif not sku_ok and not category_ok:
            return PolicyResult(Decision.BLOCK, Reason.SKU_NOT_ALLOWED, f"SKU '{item.sku}' is not authorized.")

        if not auth.financial_scope.tips_allowed and "tip" in item.sku.lower():
            return PolicyResult(Decision.BLOCK, Reason.TIPS_NOT_ALLOWED, "Tips/gratuity are not authorized by this mandate.")

        if auth.financial_scope.max_unit_price is not None and item.unit_price > auth.financial_scope.max_unit_price:
            return PolicyResult(
                Decision.BLOCK, Reason.UNIT_PRICE_EXCEEDED,
                f"Unit price {item.unit_price} for '{item.sku}' exceeds cap {auth.financial_scope.max_unit_price}.",
            )

    # 10. Quantity scope.
    if total_quantity > auth.quantity_scope.max_items:
        return PolicyResult(
            Decision.BLOCK, Reason.QUANTITY_EXCEEDED,
            f"Requested quantity {total_quantity} exceeds max_items {auth.quantity_scope.max_items}.",
        )

    # 11. Financial scope — the only check that yields RECONSENT rather than BLOCK,
    #     since a budget overrun is something the user could plausibly re-approve.
    if cart.total > auth.financial_scope.max_total:
        over_by = cart.total - auth.financial_scope.max_total
        return PolicyResult(
            Decision.RECONSENT, Reason.MAX_TOTAL_EXCEEDED,
            f"Cart total {cart.total} exceeds authorized max {auth.financial_scope.max_total} (+{over_by}).",
        )

    return PolicyResult(Decision.ALLOW, Reason.NONE, "All policy checks passed.")
