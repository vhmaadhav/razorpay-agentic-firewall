"""POST /intent/compile — 08-database-and-api-design.md #1.

This is a deterministic KEYWORD-HEURISTIC stub, not an LLM call. The real
product spec (00/02) explicitly scopes the Intent Compiler as a separate
AI-led component outside the firewall's trust boundary — the firewall must
never trust free-text "intent" for authorization, only the signed structured
mandate that comes out the other side. This stub exists purely so the demo
has something to show for step 1 of the user flow without wiring a real LLM.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/intent", tags=["intent"])


class IntentRequest(BaseModel):
    intent_text: str


class MandateProposal(BaseModel):
    max_total: int | None
    merchant_name: str | None
    quantity: int | None
    category: str | None
    substitutions_allowed: bool
    expires_in_minutes: int


class IntentResponse(BaseModel):
    mandate_proposal: MandateProposal
    confidence: float


_AMOUNT_RE = re.compile(r"(?:under|max(?:imum)?|up to|cap(?:ped)? at)?\s*₹\s*([\d,]+)|₹\s*([\d,]+)", re.IGNORECASE)
_MERCHANT_RE = re.compile(r"from\s+([A-Za-z][A-Za-z0-9 _-]*?)(?:\s+only\b|[,.]|$)", re.IGNORECASE)
_QTY_RE = re.compile(r"\b(\d+)\s+([a-zA-Z]+)")
_EXPIRY_RE = re.compile(r"expir\w*\s+in\s+(\d+)\s*min", re.IGNORECASE)


@router.post("/compile", response_model=IntentResponse)
def compile_intent(req: IntentRequest) -> IntentResponse:
    text = req.intent_text
    found_fields = 0

    amount_match = _AMOUNT_RE.search(text)
    max_total = None
    if amount_match:
        raw = (amount_match.group(1) or amount_match.group(2)).replace(",", "")
        max_total = int(raw)
        found_fields += 1

    merchant_match = _MERCHANT_RE.search(text)
    merchant_name = merchant_match.group(1).strip() if merchant_match else None
    if merchant_name:
        found_fields += 1

    qty_match = _QTY_RE.search(text)
    quantity = int(qty_match.group(1)) if qty_match else None
    category = qty_match.group(2).lower().rstrip("s") if qty_match else None
    if quantity:
        found_fields += 1

    expiry_match = _EXPIRY_RE.search(text)
    expires_in_minutes = int(expiry_match.group(1)) if expiry_match else settings.default_mandate_ttl_minutes

    substitutions_allowed = "no substitut" not in text.lower() and "substitut" in text.lower()

    confidence = round(0.5 + 0.15 * found_fields, 2)
    confidence = min(confidence, 0.98)

    return IntentResponse(
        mandate_proposal=MandateProposal(
            max_total=max_total,
            merchant_name=merchant_name,
            quantity=quantity,
            category=category,
            substitutions_allowed=substitutions_allowed,
            expires_in_minutes=expires_in_minutes,
        ),
        confidence=confidence,
    )
