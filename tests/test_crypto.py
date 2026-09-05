from app.canonical.hashing import compute_evidence_hash
from app.crypto import signature as sig
from tests.conftest import make_auth


def test_sign_verify_round_trip():
    priv, pub = sig.generate_keypair()
    envelope = make_auth(evidence_hash="", signature=None)
    envelope.evidence_hash = compute_evidence_hash(envelope.unsigned_dict())
    envelope.signature = sig.sign(envelope.evidence_hash, priv)

    assert sig.verify(envelope.evidence_hash, envelope.signature, pub) is True


def test_verify_fails_with_wrong_public_key():
    priv, _pub = sig.generate_keypair()
    _other_priv, other_pub = sig.generate_keypair()
    envelope = make_auth(evidence_hash="", signature=None)
    envelope.evidence_hash = compute_evidence_hash(envelope.unsigned_dict())
    envelope.signature = sig.sign(envelope.evidence_hash, priv)

    assert sig.verify(envelope.evidence_hash, envelope.signature, other_pub) is False


def test_tampering_after_signing_changes_hash():
    """Case 34 (Tampered Mandate): editing a signed field must change the
    recomputed evidence_hash, which is what app/policy/engine.py's signature
    check relies on to detect tampering (see its case-34 comment)."""
    priv, pub = sig.generate_keypair()
    envelope = make_auth(evidence_hash="", signature=None)
    original_hash = compute_evidence_hash(envelope.unsigned_dict())
    envelope.evidence_hash = original_hash
    envelope.signature = sig.sign(original_hash, priv)

    envelope.financial_scope.max_total = 999_999  # tamper after signing
    recomputed_hash = compute_evidence_hash(envelope.unsigned_dict())

    assert recomputed_hash != original_hash
    assert sig.verify(recomputed_hash, envelope.signature, pub) is False


def test_derive_public_key_matches_generated_pair():
    priv, pub = sig.generate_keypair()
    assert sig.derive_public_key(priv) == pub


def test_verify_rejects_garbage_input_without_raising():
    assert sig.verify("deadbeef", "not-base64!!", "also-not-base64!!") is False
