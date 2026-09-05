"""POST /policy/evaluate — 04-policy-engine.md / 08-database-and-api-design.md #4.

Stateless variant: takes a full inline envelope + cart (as in 04's example
payload) and runs the pure policy engine directly, with no DB lookups for
nonce/usage state (those default to "unused"). Useful for ad-hoc policy
testing/tooling; the stateful path used by the real checkout flow is
POST /agent/request (app/routes/agent.py -> app/policy/service.py).
"""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.models.envelope import CanonicalAuthorizationEnvelope, Cart
from app.policy.engine import evaluate_policy

router = APIRouter(prefix="/policy", tags=["policy"])


class PolicyEvaluateRequest(BaseModel):
    auth: CanonicalAuthorizationEnvelope
    cart: Cart
    current_time: str | None = None


class PolicyEvaluateResponse(BaseModel):
    decision: str
    reason: str
    message: str


@router.post("/evaluate", response_model=PolicyEvaluateResponse)
def evaluate(req: PolicyEvaluateRequest) -> PolicyEvaluateResponse:
    now = datetime.fromisoformat(req.current_time) if req.current_time else datetime.now(timezone.utc)
    result = evaluate_policy(req.auth, req.cart, current_time=now)
    return PolicyEvaluateResponse(decision=result.decision.value, reason=result.reason.value, message=result.message)
