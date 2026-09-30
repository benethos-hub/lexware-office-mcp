"""Error hierarchy surfaced to the MCP client, and how an API answer becomes one.

Every expected failure becomes a :class:`ToolError` with a short, actionable
message. A raw traceback never reaches the client, and the API key never
reaches an error message: :func:`redact` strips it from any text on the way
out. :func:`from_response` reads a refused request's body for the field it
blames and the wording it uses, in the two shapes the API answers with.

**The base class is the SDK's, and that is what carries the message across.**
See :class:`ToolError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# The SDK sorts a failing tool call into two kinds. One it was told to expect,
# whose message is handed to the model, and a crash, whose text stays on the
# server and reaches the client as "Error executing tool <name>". The sorting
# is by exception type, and this is the type that means the first kind.
from mcp.server.mcpserver.exceptions import ToolError as AnticipatedFailure

if TYPE_CHECKING:
    import httpx

__all__ = [
    "AuthError",
    "ConfigError",
    "ConflictError",
    "LocalFileError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ToolError",
    "UpstreamError",
    "ValidationError",
    "from_response",
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

    ``status`` and ``code`` are what a log line may say about the failure
    besides its class: the HTTP status the API answered with, and the API's
    own codes for what it refused. The message is written for the model and
    quotes what it sent, so the log never prints it. See ``logbook``.
    """

    status: int | None = None
    code: str = ""

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


class LocalFileError(ToolError):
    """A file on this machine could not be read or written.

    Carries the operating system's reason and never the path: the one a
    caller supplied it already knows, and the download directory describes
    this machine rather than anything the caller can act on.
    """

    def __init__(self, action: str, exc: OSError) -> None:
        # strerror is the plain reason ("Permission denied"). Without one the
        # exception was raised here with a message of its own, which is safe
        # to pass on - unless it names a file, which only the OS does.
        reason = exc.strerror or (str(exc) if exc.filename is None else "")
        super().__init__(f"Could not {action}: {reason or 'the system refused'}.")


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


# -- what the API said ----------------------------------------------------


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """The response body as a useful mapping, or an empty one.

    A bare JSON string is a body too: the files endpoint answers an unknown
    upload type with ``"Invalid or missing upload type."`` and nothing else.
    Wrapping it keeps that sentence instead of discarding it for not being an
    object.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, str):
        return {"message": body}
    return body if isinstance(body, dict) else {}


def _issues(body: dict[str, Any]) -> list[Any]:
    """Every issue the body carries, in whichever shape it used.

    Two lists are in use upstream and they share no field names.
    ``IssueList`` holds ``source``/``i18nKey``, which is what a rejected query
    parameter or a stale version comes back as. ``details`` holds
    ``field``/``violation``, which is what a refused body comes back as, and
    its own message says "please see details list for specific causes" — so
    dropping it leaves the caller reading a pointer to something they were
    not given. Measured against articles on 2026-08-21.

    A third shape is one issue flattened onto the top level, which is how the
    files endpoint reports a missing form field.
    """
    for key in ("IssueList", "details"):
        value = body.get(key)
        if isinstance(value, list):
            return value
    return [body] if body.get("source") or body.get("field") else []


def _detail_text(body: dict[str, Any]) -> str:
    """The API's own wording for a failure, without ever echoing the key."""
    parts = [str(body[key]) for key in ("errorCode", "message") if body.get(key)]
    parts.extend(_issue_texts(_issues(body)))
    text = " ".join(dict.fromkeys(part for part in parts if part)).strip()
    return f" {text}" if text else ""


# A field that was simply left out. Naming it is not the same as saying
# something is wrong with the value that was sent, and the difference decides
# whether `version` means "you did not send one" or "yours is out of date".
# The `details` shape says so in `violation`, the `IssueList` shape in
# `i18nKey`, which is where `missing_entity` arrives.
_ABSENT = ("NOTNULL", "NOTEMPTY", "NOTBLANK", "MISSING_ENTITY")


def _issue_sources(body: dict[str, Any]) -> set[str]:
    """Which fields an error blamed for a value it did not like.

    The status alone does not say what went wrong: contacts answer a missing
    role, a second billing address and a stale version all with 406. The field
    an issue names is what tells those apart.

    A field the request never sent is left out of the answer. Measured
    2026-08-21: a `PUT /v1/articles/{id}` without a body reports `version` as
    `NOTNULL`, and reading that as a version mismatch would send the caller
    off to re-read a record that is not the problem.
    """
    return {
        str(issue.get("source") or issue.get("field"))
        for issue in _issues(body)
        if isinstance(issue, dict)
        and (issue.get("source") or issue.get("field"))
        and str(issue.get("violation") or issue.get("i18nKey") or "").upper()
        not in _ABSENT
    }


def _issue_texts(issues: Any) -> list[str]:
    """Flatten the API's ``IssueList`` into readable fragments.

    A rejected query parameter comes back as
    ``{"source": "number", "i18nKey": "invalid_value"}`` and nothing else, so
    dropping either half leaves the caller guessing which field was wrong or
    what was wrong with it. A refused body names the same two things as
    ``field`` and ``violation``, plus a localized sentence that says no more
    than the violation does and is therefore left out.
    """
    if not isinstance(issues, list):
        return []
    texts = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        source = str(issue.get("source") or issue.get("field") or "")
        kind = str(
            issue.get("i18nKey") or issue.get("type") or issue.get("violation") or ""
        )
        if source and kind:
            texts.append(f"{source}: {kind}")
        elif source or kind:
            texts.append(source or kind)
    return texts


def from_response(response: httpx.Response, method: str, path: str) -> ToolError:
    """The error for a 4xx answer, in the API's own terms where it has any.

    The status alone does not say what went wrong: contacts answer a
    missing role, a second billing address and a stale version all with
    406. The body is read for the field it blames and for its wording, and
    the key never appears in either - see :func:`redact`.

    The status and the API's codes are also kept apart from the message, for
    a log line that may carry those and not the rest.
    """
    status = response.status_code
    body = _json_object(response)
    error = _refusal(status, body, method, path)
    error.status = status
    codes = [str(body.get("errorCode") or ""), *_issue_texts(_issues(body))]
    error.code = " ".join(dict.fromkeys(code for code in codes if code))
    return error


def _refusal(status: int, body: dict[str, Any], method: str, path: str) -> ToolError:
    """The error class and message for a refused request."""
    detail = _detail_text(body)
    sources = _issue_sources(body)

    if status == 401:
        return AuthError(
            "The API rejected the key. Check LXO_MCP_API_KEY, and that the "
            "key is still active in Lexware Office under Extensions, "
            "Public API."
        )
    if status == 403:
        return AuthError(
            f"The key is not permitted to {method} {path}. Check the "
            f"permissions the key was created with.{detail}"
        )
    if status == 404:
        return NotFoundError(f"{path}{detail}")
    # A stale `version` arrives as 406 naming `version`, not as 409
    # (verified 2026-08-20 by updating a contact with the version it had
    # before an earlier update), and a 409 need not be about a version at
    # all: downloading a sales document that is still a draft is refused
    # with one (verified 2026-08-21). So "read it again" is advice only
    # where a version was actually named, and every other conflict says
    # what it is without guessing why.
    if status == 406 and "version" in sources:
        return ConflictError(
            "The record changed since it was read. Read it again to get "
            f"the current version, then retry.{detail}"
        )
    if status == 409:
        return ConflictError(
            f"The API refused {method} {path} in this record's current state.{detail}"
        )
    if status == 406:
        return ValidationError(
            f"The API refused {method} {path}. The request is either not "
            f"valid or not allowed in this record's current state.{detail}"
        )
    return ValidationError(f"The API rejected {method} {path}.{detail}")
