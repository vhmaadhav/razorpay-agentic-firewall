"""POST /webhooks/razorpay — 07-razorpay-integration.md / TASK-007.

Signature verification happens on the raw request body before we touch the
parsed JSON at all. We never trust a client-side "payment success" redirect —
this webhook (or a GET /v1/payments/{id} poll) is the only source of truth
for PAYMENT_CAPTURED, per 07's "Never Trust Frontend" note.
"""
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.evidence.log import append_event
from app.models.schema import PaymentEvent, PaymentExecution, SeenWebhookEvent
from app.payment.razorpay_client import get_payment_executor

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    executor = get_payment_executor()

    if not x_razorpay_signature or not executor.verify_webhook(raw_body, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event = json.loads(raw_body)
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    amount = payment_entity.get("amount")

    if not payment_id or not order_id:
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    if db.get(SeenWebhookEvent, payment_id):
        return {"status": "duplicate_ignored"}

    db.add(SeenWebhookEvent(razorpay_payment_id=payment_id, event_type=event.get("event", "unknown")))

    execution = db.query(PaymentExecution).filter(PaymentExecution.razorpay_order_id == order_id).first()
    if not execution:
        db.commit()
        raise HTTPException(status_code=404, detail="Unknown order_id — ignoring webhook")

    signature_verified = True
    amount_mismatch = amount is not None and amount != execution.amount
    new_status = "AMOUNT_MISMATCH" if amount_mismatch else "CAPTURED"
    execution.status = new_status

    db.add(
        PaymentEvent(
            event_id=f"evt-{payment_id}",
            execution_id=execution.execution_id,
            event_type=event.get("event", "unknown"),
            payload=event,
            signature_verified=signature_verified,
        )
    )
    db.commit()

    # Walk back to the authorization_id via decision -> request chain for evidence logging.
    from app.models.schema import PolicyDecision  # local import avoids a circular top-level dependency

    decision = db.get(PolicyDecision, execution.decision_id)
    if decision:
        append_event(
            db,
            transaction_id=decision.authorization_id,
            event_type="PAYMENT_CAPTURED" if not amount_mismatch else "PAYMENT_AMOUNT_MISMATCH",
            actor="razorpay-webhook",
            payload={"payment_id": payment_id, "order_id": order_id, "amount": amount},
        )

    return {"status": "ok"}
