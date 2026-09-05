"""Glue between the pure `evaluate_policy` function and persistence/evidence.

Kept separate from app/policy/engine.py so the engine itself stays a pure,
I/O-free function (see its module docstring) while this module owns the
stateful lookups: has this nonce been seen, how many times has this mandate
already been used, and recording the outcome.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.evidence.log import append_event
from app.crypto.agent_request import request_hash
from app.crypto.signature import verify
from app.canonical.hashing import compute_evidence_hash
from app.models.envelope import Cart, CanonicalAuthorizationEnvelope
from app.models.schema import AgentRequestRow, Authorization, PolicyDecision
from app.policy.engine import Decision, evaluate_policy


def evaluate_agent_request(
    db: Session, *, authorization_id: str, agent_id: str, nonce: str, cart: Cart,
    agent_signature: str | None = None,
) -> dict:
    auth_row = db.get(Authorization, authorization_id)
    if not auth_row:
        raise HTTPException(status_code=404, detail="Unknown authorization_id")

    auth_envelope = CanonicalAuthorizationEnvelope(**auth_row.envelope)

    # Verify before looking up/consuming nonces or altering a prior decision.
    # An unauthenticated sender must not poison another agent's valid nonce.
    mandate_hash = compute_evidence_hash(auth_envelope.unsigned_dict())
    reason = None
    if (mandate_hash != auth_envelope.evidence_hash or not auth_envelope.signature
            or not verify(mandate_hash, auth_envelope.signature, auth_envelope.agent.public_key)):
        reason = "SIGNATURE_INVALID"
    elif agent_id != auth_envelope.agent.agent_id:
        reason = "AGENT_ID_MISMATCH"
    elif not auth_envelope.agent.request_public_key:
        reason = "AGENT_KEY_MISSING"
    elif not agent_signature or not verify(
        request_hash(authorization_id=authorization_id, agent_id=agent_id, nonce=nonce, cart=cart),
        agent_signature, auth_envelope.agent.request_public_key,
    ):
        reason = "AGENT_SIGNATURE_INVALID"
    if reason:
        append_event(
            db, transaction_id=authorization_id, event_type="AGENT_REQUEST_REJECTED",
            actor="agent-verifier",
            payload={"claimed_agent_id": agent_id, "reason": reason},
        )
        raise HTTPException(status_code=401, detail={
            "decision": "BLOCK", "reason": reason,
            "message": "Agent request authentication failed. Confirm the mandate and sign the complete request.",
        })

    existing = (
        db.query(AgentRequestRow)
        .filter(AgentRequestRow.authorization_id == authorization_id, AgentRequestRow.nonce == nonce)
        .first()
    )
    nonce_already_used = existing is not None

    result = evaluate_policy(
        auth_envelope,
        cart,
        current_time=datetime.now(timezone.utc),
        nonce_already_used=nonce_already_used,
        transactions_used=auth_row.used_count,
    )

    request_id = f"req-{uuid.uuid4().hex[:12]}"
    if not nonce_already_used:
        db.add(
            AgentRequestRow(
                request_id=request_id,
                authorization_id=authorization_id,
                agent_id=agent_id,
                nonce=nonce,
                cart=cart.model_dump(),
                state="VERIFIED" if result.decision == Decision.ALLOW else result.decision.value,
            )
        )
    else:
        # Replay attempt: log evidence against the mandate's chain but do not
        # create a second agent_requests row (nonce is the unique key).
        request_id = existing.request_id

    decision_id = f"dec-{uuid.uuid4().hex[:12]}"
    db.add(
        PolicyDecision(
            decision_id=decision_id,
            request_id=request_id,
            authorization_id=authorization_id,
            decision=result.decision.value,
            reason=result.reason.value,
        )
    )

    if result.decision == Decision.ALLOW:
        auth_row.used_count += 1

    db.commit()

    append_event(
        db,
        transaction_id=authorization_id,
        event_type="AGENT_REQUEST_RECEIVED" if not nonce_already_used else "REPLAY_ATTEMPT_BLOCKED",
        actor=agent_id,
        payload={"request_id": request_id, "nonce": nonce, "cart": cart.model_dump(),
                 "agent_signature": agent_signature, "signature_verified": True},
    )
    append_event(
        db,
        transaction_id=authorization_id,
        event_type="POLICY_EVALUATED",
        actor="policy-engine",
        payload={"decision": result.decision.value, "reason": result.reason.value, "message": result.message},
    )

    return {
        "request_id": request_id,
        "decision_id": decision_id,
        "decision": result.decision.value,
        "reason": result.reason.value,
        "message": result.message,
    }
