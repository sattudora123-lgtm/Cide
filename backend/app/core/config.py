import base64
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def decode_key_material(value: str) -> bytes:
    padded = value.strip() + "=" * (-len(value.strip()) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise ValueError("DATA_ENCRYPTION_KEY is not valid url-safe base64") from exc
    if len(raw) != 32:
        raise ValueError("DATA_ENCRYPTION_KEY must decode to 32 bytes")
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    data_dir: Path = Path("data")
    data_encryption_key: str
    token_encryption_key: str = ""
    jwt_secret: str
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 7
    allowed_origins: str = "http://localhost:5173"
    provider_timeout_seconds: float = 30
    provider_max_tokens: int = 1024
    heartbeat_stale_seconds: int = 30
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    max_body_bytes: int = 1_048_576

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_length(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value

    @field_validator("data_encryption_key")
    @classmethod
    def data_key_is_aes_key(cls, value: str) -> str:
        decode_key_material(value)
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def token_key_is_fernet(cls, value: str) -> str:
        if not value:
            return value
        try:
            Fernet(value.encode("ascii"))
        except Exception as exc:
            raise ValueError("TOKEN_ENCRYPTION_KEY must be a Fernet key") from exc
        return value

    @field_validator(
        "jwt_access_ttl_seconds",
        "jwt_refresh_ttl_seconds",
        "heartbeat_stale_seconds",
        "login_rate_limit",
        "login_rate_window_seconds",
        "max_body_bytes",
        "provider_max_tokens",
    )
    @classmethod
    def positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Numeric settings must be positive")
        return value

    @field_validator("provider_timeout_seconds")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("PROVIDER_TIMEOUT_SECONDS must be positive")
        return value

    def resolved_data_dir(self) -> Path:
        path = Path(self.data_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    def data_key_bytes(self) -> bytes:
        return decode_key_material(self.data_encryption_key)

    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]
