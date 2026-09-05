"""POST /payment/execute — 08-database-and-api-design.md #5.

Only ever called after a stored ALLOW decision (05-security-threat-model.md's
TOCTOU mitigation: we look up the *already-evaluated* decision + cart rather
than trusting the caller to resend cart data, so nothing can be swapped in
between policy check and order creation).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.evidence.log import append_event
from app.models.envelope import Cart
from app.models.schema import AgentRequestRow, PaymentExecution, PolicyDecision
from app.payment.razorpay_client import get_payment_executor
from app.policy.engine import Decision

router = APIRouter(prefix="/payment", tags=["payment"])


class ExecuteRequest(BaseModel):
    authorization_id: str
    request_id: str


class ExecuteResponse(BaseModel):
    order_id: str
    amount: int
    currency: str


@router.post("/execute", response_model=ExecuteResponse)
def execute_payment(req: ExecuteRequest, db: Session = Depends(get_db)) -> ExecuteResponse:
    decision_row = (
        db.query(PolicyDecision)
        .filter(PolicyDecision.request_id == req.request_id, PolicyDecision.authorization_id == req.authorization_id)
        .order_by(PolicyDecision.created_at.desc())
        .first()
    )
    if not decision_row:
        raise HTTPException(status_code=404, detail="No policy decision found for this request_id")
    if decision_row.decision != Decision.ALLOW.value:
        raise HTTPException(status_code=409, detail=f"Cannot execute payment: last decision was {decision_row.decision}")

    existing = db.query(PaymentExecution).filter(PaymentExecution.decision_id == decision_row.decision_id).first()
    if existing:
        return ExecuteResponse(order_id=existing.razorpay_order_id, amount=existing.amount, currency=existing.currency)

    request_row = db.get(AgentRequestRow, req.request_id)
    if not request_row:
        raise HTTPException(status_code=404, detail="agent_request not found")
    cart = Cart(**request_row.cart)

    executor = get_payment_executor()
    order = executor.create_order(amount=cart.total, currency=cart.currency, receipt=req.authorization_id)

    db.add(
        PaymentExecution(
            execution_id=f"exec-{uuid.uuid4().hex[:12]}",
            decision_id=decision_row.decision_id,
            razorpay_order_id=order.order_id,
            amount=order.amount,
            currency=order.currency,
            status="CREATED",
        )
    )
    db.commit()

    append_event(
        db,
        transaction_id=req.authorization_id,
        event_type="ORDER_CREATED",
        actor="payment-executor",
        payload={"order_id": order.order_id, "amount": order.amount, "currency": order.currency},
    )

    return ExecuteResponse(order_id=order.order_id, amount=order.amount, currency=order.currency)
