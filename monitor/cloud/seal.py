"""Sealed provider keys, format v1 (X25519 + HKDF-SHA256 + AES-256-GCM). The website seals; only the runner opens.

A user's provider key is encrypted on the web tier with the runner's PUBLIC key. Only the runner holds the matching
private key, so the database, the website and the API server cannot decrypt what they store.

    ephemeral key pair per secret            -> shared = X25519(ephemeral_private, runner_public)
    key   = HKDF-SHA256(shared, salt = ephemeral_public, info = TAG || key_id_be32)      (32 bytes)
    nonce = 12 random bytes
    aad   = TAG || model_row_uuid (16 bytes) || key_id_be32        (a sealed value cannot be moved to another row)
    ciphertext = AES-256-GCM(key, nonce, plaintext, aad)           (ciphertext || 16-byte tag)

The same format is written in TypeScript in frontend/lib/connect/seal.ts; tests/fixtures/seal_v1.json holds vectors made
by Node so a disagreement between the two languages fails CI. Errors are generic: they never carry a key.
"""
from __future__ import annotations

import base64
import binascii
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TAG = b"driftwatch-connect-v1"
MAX_PLAINTEXT = 512


class SealError(Exception):
    """Sealing or opening failed. The message never contains a key or any part of one."""


def _b64(value: Any, length: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise SealError("could not read a field") from None
    if length is not None and len(raw) != length:
        raise SealError("a field has the wrong length")
    return raw


def _key_id(key_id: Any) -> bytes:
    if isinstance(key_id, bool) or not isinstance(key_id, int) or not 1 <= key_id <= 1000:
        raise SealError("bad key id")
    return key_id.to_bytes(4, "big")


def _model(model_id: Any) -> bytes:
    try:
        return uuid.UUID(str(model_id)).bytes
    except ValueError:
        raise SealError("bad model id") from None


def _derive(shared: bytes, ephemeral_public: bytes, kid: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral_public, info=TAG + kid).derive(shared)


def generate_keypair() -> tuple[str, str]:
    """(private, public), both base64 of the raw 32 bytes. The private half goes only to the runner."""
    private = X25519PrivateKey.generate()
    return (
        base64.b64encode(private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode(),
        base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode(),
    )


def seal(plaintext: str, model_id: str, key_id: int, runner_public: str) -> dict[str, Any]:
    if not isinstance(plaintext, str) or not 1 <= len(plaintext) <= MAX_PLAINTEXT:
        raise SealError("bad key")
    kid, mid = _key_id(key_id), _model(model_id)
    public = X25519PublicKey.from_public_bytes(_b64(runner_public, 32))
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key = _derive(ephemeral.exchange(public), ephemeral_public, kid)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), TAG + mid + kid)
    return {
        "key_id": key_id,
        "ephemeral": base64.b64encode(ephemeral_public).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def open_sealed(runner_private: str, model_id: str, box: dict[str, Any]) -> str:
    try:
        kid, mid = _key_id(box.get("key_id")), _model(model_id)
        ephemeral_public = _b64(box.get("ephemeral"), 32)
        nonce = _b64(box.get("nonce"), 12)
        ciphertext = _b64(box.get("ciphertext"))
        if not 17 <= len(ciphertext) <= MAX_PLAINTEXT + 16:
            raise SealError("a field has the wrong length")
        private = X25519PrivateKey.from_private_bytes(_b64(runner_private, 32))
        shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
        key = _derive(shared, ephemeral_public, kid)
        return AESGCM(key).decrypt(nonce, ciphertext, TAG + mid + kid).decode("utf-8")
    except SealError:
        raise
    except (InvalidTag, ValueError, UnicodeDecodeError, AttributeError):
        raise SealError("could not open") from None
