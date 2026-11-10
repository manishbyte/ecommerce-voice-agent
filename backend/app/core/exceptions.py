"""Domain exceptions. Authorization failures deliberately look like 'not found'."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str = "", *, code: str | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class UnauthorizedAccessError(NotFoundError):
    """Record exists but belongs to someone else. Subclasses NotFoundError so callers
    cannot learn whether a foreign record exists."""

    code = "not_found"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class ActionError(AppError):
    status_code = 409
    code = "action_error"


class ProviderUnavailable(AppError):
    status_code = 503
    code = "provider_unavailable"
