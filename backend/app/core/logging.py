import json
import logging
import re

from app.core.context import request_id_var

_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]+")
_SECRET_FIELD = re.compile(
    r"(?i)(password|api_key|authorization|refresh_token|secret|token|jwt_secret)\s*[=:]\s*\S+"
)


def redact(message: str) -> str:
    message = _BEARER.sub("bearer [redacted]", message)
    return _SECRET_FIELD.sub(r"\1=[redacted]", message)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    logger = logging.getLogger("cide")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
