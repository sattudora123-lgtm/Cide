from app.core.context import request_id_var


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class CommitAndRaise(Exception):
    """Persist the current transaction, then surface this error to the client."""

    def __init__(self, error: AppError):
        super().__init__(error.message)
        self.error = error


def error_body(code: str, message: str) -> dict:
    body = {"code": code, "message": message}
    request_id = request_id_var.get()
    if request_id:
        body["request_id"] = request_id
    return {"error": body}
