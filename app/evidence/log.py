"""Append-only, hash-chained evidence log (05/08/09 docs, TASK-009).

Each event's chain_hash = SHA256(prev_chain_hash : SHA256(payload)). Altering
or deleting any past row breaks every chain_hash after it, which is what
tests/test_evidence.py exercises as the tamper-detection property.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.canonical.hashing import chain_hash, hash_json
from app.models.schema import EvidenceEvent

GENESIS_HASH = "0" * 64


def append_event(db: Session, *, transaction_id: str, event_type: str, actor: str,
                 payload: dict[str, Any], commit: bool = True) -> EvidenceEvent:
    last = (
        db.query(EvidenceEvent)
        .filter(EvidenceEvent.transaction_id == transaction_id)
        .order_by(EvidenceEvent.created_at.desc())
        .first()
    )
    prev_hash = last.chain_hash if last else GENESIS_HASH
    payload_hash = hash_json(payload)

    event = EvidenceEvent(
        evidence_id=str(uuid.uuid4()),
        transaction_id=transaction_id,
        prev_hash=prev_hash,
        payload_hash=payload_hash,
        chain_hash=chain_hash(prev_hash, payload_hash),
        event_type=event_type,
        actor=actor,
        payload=payload,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        # Flush makes this event visible to the next append in this transaction
        # while allowing callers to retain their lock until the full operation.
        db.flush()
    return event


def get_chain(db: Session, transaction_id: str) -> list[EvidenceEvent]:
    return (
        db.query(EvidenceEvent)
        .filter(EvidenceEvent.transaction_id == transaction_id)
        .order_by(EvidenceEvent.created_at.asc())
        .all()
    )


def verify_chain(events: list[EvidenceEvent]) -> bool:
    """Recomputes the hash chain from stored payloads; False means tampering."""
    prev = GENESIS_HASH
    for event in events:
        expected_payload_hash = hash_json(event.payload)
        if expected_payload_hash != event.payload_hash:
            return False
        if chain_hash(prev, event.payload_hash) != event.chain_hash:
            return False
        prev = event.chain_hash
    return True
