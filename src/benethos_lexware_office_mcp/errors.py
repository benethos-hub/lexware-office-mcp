"""Error hierarchy surfaced to the MCP client.

Every expected failure becomes a :class:`ToolError` with a short, actionable
message. A raw traceback never reaches the client, and the API key never
reaches an error message: :func:`redact` strips it from any text on the way
out.
"""

from __future__ import annotations

__all__ = [
    "AuthError",
    "ConfigError",
    "ConflictError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ToolError",
    "UpstreamError",
    "ValidationError",
    "redact",
]

_REDACTED = "<redacted>"

# Registered at startup so that any error text can be scrubbed without the
# call site having to know the secret. A module-level set keeps this available
# to `redact` from anywhere, including inside exception formatting.
_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a value that must never appear in output.

    Short values are ignored: redacting a two-character string would mangle
    unrelated text without protecting anything.
    """
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    """Replace every registered secret in ``text`` with a placeholder."""
    for secret in _SECRETS:
        text = text.replace(secret, _REDACTED)
    return text


class ToolError(Exception):
    """Base class for every failure reported to the client.

    The message is redacted on construction, so a subclass cannot leak a
    secret by interpolating one into its own text.
    """

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))

    @property
    def message(self) -> str:
        return str(self)


class ConfigError(ToolError):
    """The server is not configured well enough to serve the request."""


class AuthError(ToolError):
    """The API rejected the key (HTTP 401)."""


class PermissionDeniedError(ToolError):
    """The tool exists but the active permission tier does not allow it."""


class ValidationError(ToolError):
    """The API rejected the request as invalid (HTTP 400 or 406)."""


class NotFoundError(ToolError):
    """No resource with the given ID (HTTP 404)."""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(f"No {resource} with ID {resource_id}.")


class ConflictError(ToolError):
    """Version mismatch or locked state (HTTP 409)."""


class RateLimitError(ToolError):
    """The rate limit was hit and retrying did not clear it (HTTP 429)."""


class UpstreamError(ToolError):
    """The API failed for a reason the caller cannot act on (HTTP 5xx, network).

    Carries ``outcome_unknown`` for the case that matters most here: a write
    that may or may not have been applied. See SPECS.md section 10.2 — a
    failed POST is never retried, because a duplicate document cannot be
    undone by the client.
    """

    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        if outcome_unknown:
            message = (
                f"{message} The outcome is unknown: the request may have been "
                f"carried out even though the response was lost. Check whether "
                f"the record exists before trying again."
            )
        super().__init__(message)
        self.outcome_unknown = outcome_unknown
