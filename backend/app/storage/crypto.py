"""AES-256-GCM blobs. The key never enters the file format."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.storage.errors import StorageIntegrityError

MAGIC = b"CIDE"
VERSION = 1
_HEADER_LEN = 4 + 1 + 12


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != 32:
        raise StorageIntegrityError("Data encryption key is invalid")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return MAGIC + bytes([VERSION]) + nonce + ciphertext


def decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(key) != 32 or len(blob) < _HEADER_LEN + 16:
        raise StorageIntegrityError("Encrypted file failed authentication")
    if not blob.startswith(MAGIC) or blob[4] != VERSION:
        raise StorageIntegrityError("Encrypted file header is invalid")
    nonce = blob[5:17]
    try:
        return AESGCM(key).decrypt(nonce, blob[17:], aad)
    except Exception as exc:
        raise StorageIntegrityError("Encrypted file failed authentication") from exc
