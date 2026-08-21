"""The one API call the interface makes, and what it does with the answer."""

from __future__ import annotations

import httpx
import pytest

from benethos_lexware_office_mcp.client import ClientProvider
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import probe

PROFILE = {
    "organizationId": "11111111-2222-3333-4444-555555555555",
    "companyName": "Test Inc.",
    "taxType": "net",
    "smallBusiness": False,
}

SETTINGS = Settings(api_key="k" * 20)


@pytest.fixture(autouse=True)
def forget_the_last_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "_last", None)


def answering(response: httpx.Response) -> ClientProvider:
    return ClientProvider(SETTINGS, transport=httpx.MockTransport(lambda _r: response))


def test_without_a_key_nothing_is_asked() -> None:
    """A request that cannot carry credentials is not worth sending."""
    account, message = probe.check(Settings(), answering(httpx.Response(500)))

    assert account is None
    assert "Kein API-Schlüssel" in message


def test_a_good_answer_names_the_account() -> None:
    account, message = probe.check(
        SETTINGS, answering(httpx.Response(200, json=PROFILE))
    )

    assert account is not None
    assert account.company == "Test Inc."
    assert account.tax_type == "net"
    assert account.small_business is False
    assert message == "Verbindung steht."


def test_the_account_is_remembered_for_the_rest_of_the_session() -> None:
    """It is shown on every page afterwards, so it has to outlive the call."""
    assert probe.last_account() is None

    probe.check(SETTINGS, answering(httpx.Response(200, json=PROFILE)))

    remembered = probe.last_account()
    assert remembered is not None and remembered.label == "Test Inc."


def test_a_nameless_account_still_has_a_label() -> None:
    account, _ = probe.check(SETTINGS, answering(httpx.Response(200, json={})))

    assert account is not None and account.label == "unbekanntes Konto"
    assert account.small_business is None


def test_a_refusal_is_reported_rather_than_raised() -> None:
    account, message = probe.check(SETTINGS, answering(httpx.Response(401)))

    assert account is None
    assert "Schlüssel wurde abgelehnt" in message


def test_the_key_is_never_in_the_message() -> None:
    """The interface exists partly so the key need never be seen."""
    settings = Settings(api_key="the-secret-key-value")
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(400, text="bad key the-secret-key-value")
        ),
    )

    _, message = probe.check(settings, provider)

    assert "the-secret-key-value" not in message


def test_a_machine_with_no_network_is_told_so() -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing listening")

    provider = ClientProvider(SETTINGS, transport=httpx.MockTransport(refuse))

    account, message = probe.check(SETTINGS, provider)

    assert account is None
    assert "fehlgeschlagen" in message
