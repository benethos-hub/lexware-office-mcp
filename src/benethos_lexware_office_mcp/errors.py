"""Error hierarchy surfaced to the MCP client.

Every expected failure becomes a :class:`ToolError` with a short, actionable
message. A raw traceback never reaches the client, and the API key never
reaches an error message: :func:`redact` strips it from any text on the way
out.

**The base class is the SDK's, and that is what carries the message across.**
See :class:`ToolError`.
"""

from __future__ import annotations

# The SDK sorts a failing tool call into two kinds. One it was told to expect,
# whose message is handed to the model, and a crash, whose text stays on the
# server and reaches the client as "Error executing tool <name>". The sorting
# is by exception type, and this is the type that means the first kind.
from mcp.server.mcpserver.exceptions import ToolError as AnticipatedFailure

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


class ToolError(AnticipatedFailure):
    """Base class for every failure reported to the client.

    The message is redacted on construction, so a subclass cannot leak a
    secret by interpolating one into its own text.

    Deriving from the SDK's own tool error is what makes the message travel.
    An exception of any other type is read as a crash, and the model is told
    only which tool failed - so a hierarchy of plain :class:`Exception`
    subclasses would write these sentences and never deliver one. The
    :class:`ValueError` raised for a bad preset or a bad rate is on the other
    side of that line on purpose: it is a mistake in the configuration of the
    process, not an answer for the model.
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
    """Nothing there (HTTP 404).

    Two forms, because a 404 answers two different questions. A caller that
    looked something up by id gets told which id: ``NotFoundError("voucher",
    "abc")``. A caller that asked for a path gets told the path, which is the
    only thing the client knows — guessing an id out of it produces messages
    like "No resource with ID file" for ``/v1/invoices/{id}/file``.
    """

    def __init__(self, resource: str, resource_id: str | None = None) -> None:
        if resource_id is None:
            super().__init__(f"The API has nothing at {resource}.")
        else:
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
