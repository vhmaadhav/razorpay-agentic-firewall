"""Razorpay integration — 07-razorpay-integration.md / TASK-006 / TASK-007.

Two implementations share one interface (`create_order`, `verify_webhook`):

- `LiveRazorpayClient` wraps the official `razorpay` SDK against Test Mode,
  used once RAZORPAY_KEY_ID/SECRET are set in the environment.
- `MockRazorpayClient` fabricates deterministic order IDs and HMAC-signed
  webhook payloads locally, so the full ALLOW -> order -> webhook -> captured
  flow can be demoed/tested with zero network calls and no credentials.

`get_payment_executor()` picks whichever is configured — nothing else in the
codebase needs to know which one is active.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import settings


@dataclass
class OrderResult:
    order_id: str
    amount: int
    currency: str
    status: str
    receipt: str


class PaymentExecutor(Protocol):
    def create_order(self, amount: int, currency: str, receipt: str) -> OrderResult: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool: ...

    def build_test_webhook(self, order: OrderResult, event: str = "payment.captured") -> tuple[bytes, str]:
        """Only meaningful for the mock — builds a signed payload for demo scripts."""
        ...


class LiveRazorpayClient:
    def __init__(self, key_id: str, key_secret: str, webhook_secret: str | None):
        import razorpay  # imported lazily so the mock path has no hard dependency

        self._client = razorpay.Client(auth=(key_id, key_secret))
        self._webhook_secret = webhook_secret

    def create_order(self, amount: int, currency: str, receipt: str) -> OrderResult:
        order = self._client.order.create(
            {"amount": amount, "currency": currency, "receipt": receipt, "payment_capture": 1}
        )
        return OrderResult(
            order_id=order["id"], amount=order["amount"], currency=order["currency"],
            status=order["status"], receipt=receipt,
        )

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False
        expected = hmac.new(self._webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def build_test_webhook(self, order: OrderResult, event: str = "payment.captured") -> tuple[bytes, str]:
        raise NotImplementedError("Live mode: trigger a real test-mode payment and let Razorpay send the webhook.")


class MockRazorpayClient:
    """Deterministic stand-in used until real test-mode keys are supplied."""

    MOCK_SECRET = "mock-webhook-secret-do-not-use-in-prod"

    def create_order(self, amount: int, currency: str, receipt: str) -> OrderResult:
        return OrderResult(
            order_id=f"order_MOCK{uuid.uuid4().hex[:14]}",
            amount=amount, currency=currency, status="created", receipt=receipt,
        )

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        expected = hmac.new(self.MOCK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def build_test_webhook(self, order: OrderResult, event: str = "payment.captured") -> tuple[bytes, str]:
        payment_id = f"pay_MOCK{uuid.uuid4().hex[:14]}"
        body: dict[str, Any] = {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": order.order_id,
                        "amount": order.amount,
                        "currency": order.currency,
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.MOCK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        return raw, signature


def get_payment_executor() -> PaymentExecutor:
    if settings.razorpay_configured:
        return LiveRazorpayClient(
            settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret
        )
    return MockRazorpayClient()
