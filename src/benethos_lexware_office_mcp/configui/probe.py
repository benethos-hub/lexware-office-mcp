"""Asking the API once whether the key works, and which account it opens.

Two questions in one call. The second is the one that matters here: an
interface that hands out permission to change accounting records has to say
**whose** records, and the account name is the only thing that answers it.
The name is remembered for as long as the interface runs and shown on every
page after that, so the answer stays in view while the permissions are edited.

The call goes through ``LexwareClient`` like every other request this project
makes, so it passes the one token bucket. Nothing here builds its own HTTP
client, and nothing runs it on its own: a page load never reaches the API, a
person presses the button.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from ..client import ClientProvider
from ..config import Settings
from ..errors import AuthError, ToolError, redact

__all__ = ["Account", "check", "last_account"]

_lock = threading.Lock()
_last: Account | None = None


@dataclass(frozen=True, slots=True)
class Account:
    """What one successful check learned about the connected account."""

    company: str
    tax_type: str = ""
    small_business: bool | None = None

    @property
    def label(self) -> str:
        return self.company or "unbekanntes Konto"


def last_account() -> Account | None:
    """The account of the last successful check in this process."""
    with _lock:
        return _last


def check(
    settings: Settings, provider: ClientProvider | None = None
) -> tuple[Account | None, str]:
    """One ``GET /v1/profile``. Returns the account, or why there is none.

    The message is German and complete on its own, because it is shown as the
    whole answer. Secrets are redacted from it the same way they are in a tool
    result — an error carrying the key would defeat the point of never
    displaying it.

    ``provider`` is injectable for tests, the same way the server takes one.
    """
    if not settings.api_key:
        return None, "Kein API-Schlüssel hinterlegt. Unter Zugangsdaten eintragen."
    try:
        payload = asyncio.run(_ask(settings, provider))
    except AuthError as exc:
        return None, f"Der Schlüssel wurde abgelehnt: {redact(str(exc))}"
    except ToolError as exc:
        # Everything else the client already turns into a ToolError, a failed
        # connection included, so there is no second kind of failure to catch.
        return None, f"Der Aufruf ist fehlgeschlagen: {redact(str(exc))}"

    account = Account(
        company=str(payload.get("companyName") or ""),
        tax_type=str(payload.get("taxType") or ""),
        small_business=(
            bool(payload["smallBusiness"]) if "smallBusiness" in payload else None
        ),
    )
    global _last
    with _lock:
        _last = account
    return account, "Verbindung steht."


async def _ask(
    settings: Settings, provider: ClientProvider | None
) -> dict[str, object]:
    """One request through the shared client, which is the only kind there is.

    A bare ``httpx`` call here would sit outside the one token bucket that
    ``client.py`` owns, and the upstream limit is counted per account rather
    than per program. See SPECS.md section 10.1.
    """
    owned = provider is None
    provider = provider or ClientProvider(settings)
    try:
        return await provider.get().profile()
    finally:
        if owned:
            await provider.aclose()
