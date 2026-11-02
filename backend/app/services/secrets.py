from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError


def encrypt_secret(fernet_key: str, plaintext: str) -> str:
    if not fernet_key:
        raise AppError(503, "encryption_not_configured", "Provider key encryption is not configured")
    return Fernet(fernet_key.encode("ascii")).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(fernet_key: str, ciphertext: str) -> str:
    if not fernet_key:
        raise AppError(503, "encryption_not_configured", "Provider key encryption is not configured")
    try:
        return Fernet(fernet_key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise AppError(500, "storage_integrity_error", "A stored provider key could not be read") from exc
