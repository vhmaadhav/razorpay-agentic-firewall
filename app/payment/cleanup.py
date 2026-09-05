"""Flag unconfirmed orders without making assumptions about provider outcome."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.db import lock_authorization
from app.evidence.log import append_event
from app.models.schema import PaymentExecution, PaymentEvent, PolicyDecision

logger = logging.getLogger(__name__)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def flag_stale_payments(session_factory, *, timeout_seconds: int, batch_size: int,
                        now: datetime | None = None) -> int:
    """One bounded sweep. Recheck every candidate under the webhook's lock."""
    if timeout_seconds <= 0 or batch_size <= 0:
        raise ValueError("Payment timeout and cleanup batch size must be positive")
    observed_at = utc(now or datetime.now(timezone.utc))
    cutoff = observed_at - timedelta(seconds=timeout_seconds)
    with session_factory() as db:
        has_webhook = db.query(PaymentEvent.event_id).filter(
            PaymentEvent.execution_id == PaymentExecution.execution_id,
        ).exists()
        candidates = (
            db.query(PaymentExecution.execution_id, PolicyDecision.authorization_id)
            .join(PolicyDecision, PaymentExecution.decision_id == PolicyDecision.decision_id)
            .filter(PaymentExecution.status == "CREATED", PaymentExecution.created_at <= cutoff, ~has_webhook)
            .order_by(PaymentExecution.created_at, PaymentExecution.execution_id)
            .limit(batch_size).all()
        )

    flagged = 0
    for execution_id, authorization_id in candidates:
        with session_factory() as db:
            lock_authorization(db, authorization_id)
            execution = db.get(PaymentExecution, execution_id)
            if (execution is None or execution.status != "CREATED"
                    or utc(execution.created_at) > cutoff
                    or db.query(PaymentEvent).filter_by(execution_id=execution_id).first() is not None):
                continue
            execution.status = "STALE"
            append_event(
                db, transaction_id=authorization_id, event_type="PAYMENT_STALE",
                actor="payment-cleanup",
                payload={
                    "execution_id": execution_id, "order_id": execution.razorpay_order_id,
                    "previous_status": "CREATED", "status": "STALE",
                    "created_at": utc(execution.created_at).isoformat(),
                    "observed_at": observed_at.isoformat(), "timeout_seconds": timeout_seconds,
                },
            )  # Commit the flag and its evidence atomically before releasing lock.
            flagged += 1
    return flagged


async def run_payment_cleanup(stop: asyncio.Event, session_factory, *, timeout_seconds: int,
                              interval_seconds: int, batch_size: int) -> None:
    """Wait between sweeps, retry failures, and finish an active sweep on shutdown."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            return
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        try:
            count = await asyncio.to_thread(
                flag_stale_payments, session_factory,
                timeout_seconds=timeout_seconds, batch_size=batch_size,
            )
            if count:
                logger.info("Flagged %s stale payment orders", count)
        except Exception:
            logger.exception("Payment cleanup sweep failed; retrying next interval")
