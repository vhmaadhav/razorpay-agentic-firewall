"""Versioned Ed25519 request protocol, shared by ingestion and Python clients."""
from app.canonical.hashing import hash_json
from app.crypto.signature import sign
from app.models.envelope import Cart


def request_hash(*, authorization_id: str, agent_id: str, nonce: str, cart: Cart) -> str:
    """Hash the normalized cart, including defaults and null categories.

    The domain binds signatures to this endpoint/protocol. Sign the lowercase
    SHA-256 hex string as ASCII, matching the existing Ed25519 helpers.
    """
    return hash_json({
        "domain": "agent-request.v1",
        "authorization_id": authorization_id,
        "agent_id": agent_id,
        "nonce": nonce,
        "cart": cart.model_dump(),
    })


def sign_request(payload: dict, private_key: str) -> dict:
    """Return a signed copy without changing the caller's payload."""
    digest = request_hash(
        authorization_id=payload["authorization_id"], agent_id=payload["agent_id"],
        nonce=payload["nonce"], cart=Cart(**payload["cart"]),
    )
    return {**payload, "agent_signature": sign(digest, private_key)}
