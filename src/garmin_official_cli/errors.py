"""Error hierarchy. Each error maps to one envelope ``type`` and one exit code."""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_API = 4


class CliError(Exception):
    """Base class for errors rendered as ``{"ok":false,"error":{...}}``."""

    error_type = "internal"
    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {k: v for k, v in details.items() if v is not None}

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.error_type, "message": self.message, **self.details}


class InternalError(CliError):
    error_type = "internal"
    exit_code = EXIT_INTERNAL


class UsageError(CliError):
    error_type = "usage"
    exit_code = EXIT_USAGE


class AuthError(CliError):
    error_type = "auth"
    exit_code = EXIT_AUTH


class ApiError(CliError):
    error_type = "api"
    exit_code = EXIT_API


class UnsupportedError(CliError):
    """A feature the official Garmin APIs cannot provide (exit 4, by contract)."""

    error_type = "unsupported"
    exit_code = EXIT_API

    def __init__(self, message: str, *, reason: str, tier_required: str, **details: Any) -> None:
        super().__init__(message, reason=reason, tier_required=tier_required, **details)
