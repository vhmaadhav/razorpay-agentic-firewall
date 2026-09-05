import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.evidence.log import append_event, get_chain, verify_chain
from app.models import schema  # noqa: F401  (registers tables)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_chain_builds_and_verifies(db_session):
    append_event(db_session, transaction_id="tx-1", event_type="MANDATE_SIGNED", actor="user_789", payload={"a": 1})
    append_event(db_session, transaction_id="tx-1", event_type="AGENT_REQUEST_RECEIVED", actor="agent_xyz", payload={"b": 2})
    append_event(db_session, transaction_id="tx-1", event_type="POLICY_EVALUATED", actor="policy-engine", payload={"decision": "ALLOW"})

    events = get_chain(db_session, "tx-1")
    assert len(events) == 3
    assert verify_chain(events) is True


def test_tampering_a_past_event_breaks_the_chain(db_session):
    """Phase 5 Definition of Done: 'Tamper test: altering a past event breaks
    chain hash.'"""
    append_event(db_session, transaction_id="tx-2", event_type="MANDATE_SIGNED", actor="user_789", payload={"a": 1})
    append_event(db_session, transaction_id="tx-2", event_type="AGENT_REQUEST_RECEIVED", actor="agent_xyz", payload={"b": 2})

    events = get_chain(db_session, "tx-2")
    assert verify_chain(events) is True

    events[0].payload = {"a": 999}  # tamper with the first event's payload
    assert verify_chain(events) is False


def test_chains_are_independent_per_transaction(db_session):
    append_event(db_session, transaction_id="tx-A", event_type="MANDATE_SIGNED", actor="u1", payload={"x": 1})
    append_event(db_session, transaction_id="tx-B", event_type="MANDATE_SIGNED", actor="u2", payload={"x": 1})

    chain_a = get_chain(db_session, "tx-A")
    chain_b = get_chain(db_session, "tx-B")
    assert len(chain_a) == 1 and len(chain_b) == 1
    assert chain_a[0].chain_hash == chain_b[0].chain_hash  # same genesis + same payload -> same hash
