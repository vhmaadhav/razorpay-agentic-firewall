"""POST /agent/request — 08-database-and-api-design.md #3.

Per 04-policy-engine.md the evaluation is "internal or triggered by
/agent/request" — for this MVP we run it synchronously here (see
app/policy/service.py) rather than requiring a second round-trip, and also
expose /policy/evaluate separately for direct/internal calls.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.envelope import Cart
from app.policy.service import evaluate_agent_request

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequestIn(BaseModel):
    authorization_id: str
    nonce: str
    agent_id: str
    cart: Cart
    agent_signature: str | None = None


class AgentRequestOut(BaseModel):
    request_id: str
    status: str
    decision: str
    reason: str
    message: str


@router.post("/request", response_model=AgentRequestOut)
def submit_agent_request(req: AgentRequestIn, db: Session = Depends(get_db)) -> AgentRequestOut:
    result = evaluate_agent_request(
        db, authorization_id=req.authorization_id, agent_id=req.agent_id, nonce=req.nonce,
        cart=req.cart, agent_signature=req.agent_signature,
    )
    return AgentRequestOut(
        request_id=result["request_id"],
        status="RECEIVED",
        decision=result["decision"],
        reason=result["reason"],
        message=result["message"],
    )
