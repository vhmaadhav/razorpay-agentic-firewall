"""Canonical JSON serialization + hashing for the Authorization Envelope.

The evidence_hash is computed over every field except `evidence_hash` and
`signature` themselves, using sorted keys / no whitespace so that signer and
verifier always hash byte-identical input.
"""
import hashlib
import json
from typing import Any

EXCLUDED_FIELDS = {"evidence_hash", "signature"}


def canonicalize(payload: dict[str, Any]) -> bytes:
    signable = {k: v for k, v in payload.items() if k not in EXCLUDED_FIELDS}
    return json.dumps(signable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_evidence_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def chain_hash(prev_hash: str, payload_hash: str) -> str:
    return hashlib.sha256(f"{prev_hash}:{payload_hash}".encode("utf-8")).hexdigest()


def hash_json(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
