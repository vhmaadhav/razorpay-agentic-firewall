"""SQLAlchemy tables per 08-database-and-api-design.md."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Authorization(Base):
    __tablename__ = "authorizations"

    authorization_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    envelope: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    max_transactions: Mapped[int] = mapped_column(Integer, default=1)
    nonce: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MandateRevocation(Base):
    """Separate state preserves signed envelopes and upgrades existing databases."""

    __tablename__ = "mandate_revocations"

    authorization_id: Mapped[str] = mapped_column(
        String, ForeignKey("authorizations.authorization_id"), primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(500))
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRequestRow(Base):
    __tablename__ = "agent_requests"
    __table_args__ = (UniqueConstraint("authorization_id", "nonce", name="uq_auth_nonce"),)

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String, ForeignKey("authorizations.authorization_id"))
    agent_id: Mapped[str] = mapped_column(String)
    nonce: Mapped[str] = mapped_column(String)
    cart: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("agent_requests.request_id"))
    authorization_id: Mapped[str] = mapped_column(String, ForeignKey("authorizations.authorization_id"))
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentExecution(Base):
    __tablename__ = "payment_executions"

    execution_id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String, ForeignKey("policy_decisions.decision_id"))
    razorpay_order_id: Mapped[str] = mapped_column(String, unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[str] = mapped_column(String, default="CREATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String, ForeignKey("payment_executions.execution_id"))
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceEvent(Base):
    __tablename__ = "evidence_events"

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    prev_hash: Mapped[str] = mapped_column(String)
    payload_hash: Mapped[str] = mapped_column(String)
    chain_hash: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SeenWebhookEvent(Base):
    """De-dupe table for Razorpay webhook deliveries (replay / duplicate delivery guard)."""

    __tablename__ = "seen_webhook_events"

    razorpay_payment_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
