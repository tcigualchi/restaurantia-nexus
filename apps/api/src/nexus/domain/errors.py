"""Domain errors mapped to HTTP status codes by the API layer."""

from __future__ import annotations


class DomainError(Exception):
    """Base class. ``code`` is a stable machine-readable identifier."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, object] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class Gone(DomainError):
    """Resource exists but can no longer be acted upon (e.g. expired approval)."""

    status_code = 410
    code = "gone"


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int = 60):
        super().__init__(message, details={"retry_after_seconds": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class RetryableError(Exception):
    """Raised by event handlers when a precondition is not met *yet*."""
