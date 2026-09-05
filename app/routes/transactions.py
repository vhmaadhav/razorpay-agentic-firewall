"""GET /transactions/{id} and /transactions/{id}/evidence — 08 #7, #8."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.evidence.log import get_chain, verify_chain
from app.models.schema import AgentRequestRow, Authorization, MandateRevocation, PaymentExecution, PolicyDecision
from datetime import timezone

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/{authorization_id}")
def get_transaction(authorization_id: str, db: Session = Depends(get_db)) -> dict:
    auth_row = db.get(Authorization, authorization_id)
    if not auth_row:
        raise HTTPException(status_code=404, detail="Unknown authorization_id")

    requests = (
        db.query(AgentRequestRow).filter(AgentRequestRow.authorization_id == authorization_id).all()
    )
    decisions = (
        db.query(PolicyDecision).filter(PolicyDecision.authorization_id == authorization_id).all()
    )
    decision_ids = [d.decision_id for d in decisions]
    payments = (
        db.query(PaymentExecution).filter(PaymentExecution.decision_id.in_(decision_ids)).all()
        if decision_ids
        else []
    )

    revocation = db.get(MandateRevocation, authorization_id)
    return {
        "authorization_id": authorization_id,
        "status": "REVOKED" if revocation else "SIGNED",
        "revocation": {
            "reason": revocation.reason,
            "revoked_at": revocation.revoked_at.replace(tzinfo=timezone.utc).isoformat(),
        } if revocation else None,
        "mandate": auth_row.envelope,
        "used_count": auth_row.used_count,
        "requests": [
            {"request_id": r.request_id, "agent_id": r.agent_id, "nonce": r.nonce, "cart": r.cart, "state": r.state}
            for r in requests
        ],
        "decisions": [
            {"decision_id": d.decision_id, "request_id": d.request_id, "decision": d.decision, "reason": d.reason}
            for d in decisions
        ],
        "payments": [
            {"order_id": p.razorpay_order_id, "amount": p.amount, "currency": p.currency, "status": p.status}
            for p in payments
        ],
    }


@router.get("/{authorization_id}/evidence")
def get_evidence(authorization_id: str, db: Session = Depends(get_db)) -> dict:
    events = get_chain(db, authorization_id)
    return {
        "authorization_id": authorization_id,
        "chain_valid": verify_chain(events),
        "events": [
            {
                "evidence_id": e.evidence_id,
                "event_type": e.event_type,
                "actor": e.actor,
                "prev_hash": e.prev_hash,
                "chain_hash": e.chain_hash,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }
