"""How a refused API answer becomes a ``ToolError``.

:func:`from_response` reads a refused request's body for the field it blames
and the wording it uses, in the two shapes the API answers with. The key
never appears in what it builds - every message passes ``errors.redact``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    ToolError,
    ValidationError,
)

if TYPE_CHECKING:
    import httpx

__all__ = ["from_response"]


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
            "Public API. A key changed since the server started is used once "
            "the client starts it again, Claude Desktop by being quit from "
            "the tray."
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
