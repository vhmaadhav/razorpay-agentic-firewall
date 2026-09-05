"""POST /authorization/confirm — 08-database-and-api-design.md #2.

Acts as the "Trusted Surface" from 02-system-architecture.md: it takes the
(already user-reviewed) mandate proposal, assigns it an authorization_id +
nonce if missing, computes evidence_hash, signs it, and persists it. In a
real deployment the private key would live in a passkey/HSM the user
controls; here we generate (or accept) an Ed25519 keypair server-side as the
MVP stand-in noted in 05-security-threat-model.md ("MVP: Static agent keys").
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.orm import Session

from app.canonical.hashing import compute_evidence_hash
from app.config import settings
from app.crypto import signature as crypto_signature
from app.db import get_db, lock_authorization
from app.evidence.log import append_event
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
from app.models.schema import Authorization, MandateRevocation

router = APIRouter(prefix="/authorization", tags=["authorization"])


class ConfirmRequest(BaseModel):
    mandate: dict[str, Any]
    agent_public_key: str
    signing_private_key: str | None = None

    @field_validator("agent_public_key")
    @classmethod
    def validate_agent_key(cls, value: str) -> str:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))
        except (ValueError, TypeError) as exc:
            raise ValueError("agent_public_key must be a base64 Ed25519 public key") from exc
        return value


class ConfirmResponse(BaseModel):
    authorization_id: str
    status: str
    public_key: str
    evidence_hash: str


def _build_envelope(mandate: dict[str, Any], agent_public_key: str) -> CanonicalAuthorizationEnvelope:
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=mandate.get("expires_in_minutes", settings.default_mandate_ttl_minutes))

    return CanonicalAuthorizationEnvelope(
        version="1.0",
        authorization_id=mandate.get("authorization_id") or f"auth-{uuid.uuid4().hex[:12]}",
        principal=Principal(
            user_id=mandate.get("user_id", "demo-user"),
            identity_provider=mandate.get("identity_provider", "razorpay"),
        ),
        agent=Agent(
            agent_id=mandate.get("agent_id", "demo-agent"),
            provider=mandate.get("agent_provider", "demo"),
            public_key=agent_public_key,
            trust_level=mandate.get("trust_level", "user_key"),
        ),
        merchant_scope=MerchantScope(
            merchant_ids=mandate.get("merchant_ids")
            or ([mandate["merchant_name"]] if mandate.get("merchant_name") else []),
            merchant_categories=mandate.get("merchant_categories", []),
        ),
        product_scope=ProductScope(
            allowed_skus=mandate.get("allowed_skus", []),
            allowed_categories=mandate.get("allowed_categories")
            or ([mandate["category"]] if mandate.get("category") else []),
            forbidden_skus=mandate.get("forbidden_skus", []),
            substitutions_allowed=mandate.get("substitutions_allowed", False),
        ),
        financial_scope=FinancialScope(
            currency=mandate.get("currency", "INR"),
            max_total=mandate["max_total"],
            max_unit_price=mandate.get("max_unit_price"),
            shipping_included=mandate.get("shipping_included", True),
            tax_included=mandate.get("tax_included", True),
            tips_allowed=mandate.get("tips_allowed", False),
        ),
        quantity_scope=QuantityScope(max_items=mandate.get("quantity") or mandate.get("max_items", 999)),
        temporal_scope=TemporalScope(
            issued_at=mandate.get("issued_at") or now.isoformat(),
            expires_at=mandate.get("expires_at") or (now + ttl).isoformat(),
        ),
        execution_scope=ExecutionScope(
            max_transactions=mandate.get("max_transactions", 1),
            reusable=mandate.get("reusable", False),
        ),
        nonce=mandate.get("nonce") or uuid.uuid4().hex,
        evidence_hash="",
        signature=None,
    )


@router.post("/confirm", response_model=ConfirmResponse)
def confirm_authorization(req: ConfirmRequest, db: Session = Depends(get_db)) -> ConfirmResponse:
    private_key = req.signing_private_key
    if not private_key:
        private_key, _ = crypto_signature.generate_keypair()
    public_key = crypto_signature.derive_public_key(private_key)

    envelope = _build_envelope(req.mandate, public_key)
    # The mandate signer approves the agent key; the agent never receives
    # the mandate signing key and cannot grant itself different constraints.
    envelope.agent.request_public_key = req.agent_public_key
    evidence_hash = compute_evidence_hash(envelope.unsigned_dict())
    envelope.evidence_hash = evidence_hash
    envelope.signature = crypto_signature.sign(evidence_hash, private_key)

    if db.get(Authorization, envelope.authorization_id):
        raise HTTPException(status_code=409, detail="authorization_id already exists")

    row = Authorization(
        authorization_id=envelope.authorization_id,
        user_id=envelope.principal.user_id,
        envelope=envelope.model_dump(),
        signature=envelope.signature,
        issued_at=datetime.fromisoformat(envelope.temporal_scope.issued_at),
        expires_at=datetime.fromisoformat(envelope.temporal_scope.expires_at),
        used_count=0,
        max_transactions=envelope.execution_scope.max_transactions,
        nonce=envelope.nonce,
    )
    db.add(row)
    db.commit()

    append_event(
        db,
        transaction_id=envelope.authorization_id,
        event_type="MANDATE_SIGNED",
        actor=envelope.principal.user_id,
        payload=envelope.model_dump(),
    )

    return ConfirmResponse(
        authorization_id=envelope.authorization_id,
        status="SIGNED",
        public_key=public_key,
        evidence_hash=evidence_hash,
    )


class RevokeRequest(BaseModel):
    reason: str = Field(default="operator_request", min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class RevokeResponse(BaseModel):
    authorization_id: str
    status: str
    reason: str
    revoked_at: datetime


@router.post("/{authorization_id}/revoke", response_model=RevokeResponse)
def revoke_authorization(
    authorization_id: str, req: RevokeRequest, db: Session = Depends(get_db),
) -> RevokeResponse:
    # Same trusted local operator boundary as /confirm. Never accept an
    # agent-supplied actor as proof of principal identity.
    lock_authorization(db, authorization_id)
    row = db.get(MandateRevocation, authorization_id)
    if row is None:
        row = MandateRevocation(
            authorization_id=authorization_id, reason=req.reason,
            revoked_at=datetime.now(timezone.utc),
        )
        db.add(row)
        # append_event commits the revocation and its evidence together.
        append_event(
            db, transaction_id=authorization_id, event_type="MANDATE_REVOKED",
            actor="trusted-operator",
            payload={"authorization_id": authorization_id, "reason": row.reason,
                     "revoked_at": row.revoked_at.isoformat()},
        )
    else:
        db.commit()
    return RevokeResponse(
        authorization_id=authorization_id, status="REVOKED", reason=row.reason,
        revoked_at=row.revoked_at.replace(tzinfo=timezone.utc),
    )
