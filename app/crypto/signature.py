"""Ed25519 sign/verify helpers for the canonical mandate.

TASK-003 (11-agent-task-breakdown.md): sign(payload, private_key) -> signature,
verify(payload, signature, public_key) -> bool. We sign the evidence_hash
bytes (hex-encoded ASCII), not the raw JSON, so the signature is bound to the
exact canonicalization in app/canonical/hashing.py.
"""
import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64) for demo/test key issuance."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_b64 = base64.b64encode(
        private_key.private_bytes_raw()
    ).decode("ascii")
    pub_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")
    return priv_b64, pub_b64


def sign(evidence_hash: str, private_key_b64: str) -> str:
    raw = base64.b64decode(private_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    signature = private_key.sign(evidence_hash.encode("ascii"))
    return base64.b64encode(signature).decode("ascii")


def derive_public_key(private_key_b64: str) -> str:
    raw = base64.b64decode(private_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    return base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")


def verify(evidence_hash: str, signature_b64: str, public_key_b64: str) -> bool:
    try:
        raw_pub = base64.b64decode(public_key_b64, validate=True)
        raw_sig = base64.b64decode(signature_b64, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(raw_pub)
        public_key.verify(raw_sig, evidence_hash.encode("ascii"))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
