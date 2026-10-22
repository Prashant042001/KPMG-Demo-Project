"""Domain errors. Messages are safe to return to the client: they never contain file-system paths or cell values."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class FileValidationError(AppError):
    status_code = 422
    code = "file_validation_failed"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class JobNotFoundError(AppError):
    status_code = 404
    code = "job_not_found"


class JobNotReadyError(AppError):
    status_code = 409
    code = "job_not_ready"
