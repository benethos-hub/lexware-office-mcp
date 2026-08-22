"""The local server: routing, the two guards, and what each action writes.

A real ``ThreadingHTTPServer`` on a loopback port, driven through a real
cookie jar. Nothing here reaches the API — ``probe.check`` is replaced, which
is the only function in the interface that would.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import probe, transfer
from benethos_lexware_office_mcp.configui.app import ConfigServer, Handler
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.envfile import read_env_file
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools

ACCOUNT = probe.Account(company="Test Inc.", tax_type="net")


def fake_check(settings: Settings) -> tuple[probe.Account, str]:
    """Stands in for the one function here that would reach the API.

    It remembers the account the way the real one does, because the chip on
    every page is drawn from that memory.
    """
    probe._last = ACCOUNT
    return ACCOUNT, "Verbindung steht."


class Browser:
    """Just enough of one: a cookie jar, forms, and the CSRF token."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def get(self, path: str) -> tuple[int, str, dict[str, str]]:
        return self._open(urllib.request.Request(self.base + path))

    def token(self) -> str:
        """Any page carries it: it is the session cookie, echoed back."""
        _, body, _ = self.get("/")
        found = re.search(r'name="_csrf" value="([^"]+)"', body)
        assert found, "the page carried no CSRF token"
        return found.group(1)

    def post(
        self,
        path: str,
        fields: dict[str, object],
        *,
        origin: bool = True,
        csrf: str | None = "",
    ) -> tuple[int, str, dict[str, str]]:
        pairs: list[tuple[str, str]] = []
        for key, value in fields.items():
            if isinstance(value, (list, tuple)):
                pairs.extend((key, str(item)) for item in value)
            else:
                pairs.append((key, str(value)))
        if csrf == "":
            csrf = self.token()
        if csrf is not None:
            pairs.append(("_csrf", csrf))
        request = urllib.request.Request(
            self.base + path, data=urlencode(pairs).encode("utf-8")
        )
        if origin:
            request.add_header("Origin", self.base)
        return self._open(request)

    def _open(self, request: urllib.request.Request) -> tuple[int, str, dict[str, str]]:
        try:
            with self.opener.open(request) as response:
                return (
                    response.status,
                    response.read().decode("utf-8"),
                    dict(response.headers),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


@pytest.fixture
def installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_configuration_from_this_machine: None,
) -> Installation:
    monkeypatch.setattr(probe, "_last", None)
    monkeypatch.setattr(probe, "check", fake_check)
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_PAGE_SIZE=50\n", encoding="utf-8")
    settings = Settings(
        api_key="secret-value", page_size=50, tool_policy_path=tmp_path / "tools.json"
    )
    return Installation(settings=settings, env_path=env, cwd=tmp_path)


@pytest.fixture
def browser(installation: Installation) -> Iterator[Browser]:
    server = ConfigServer(("127.0.0.1", 0), Handler)
    server.installation = installation
    # A short poll interval only so that shutdown() returns promptly: the
    # default half second would be spent in the teardown of every test here.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Browser(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def note(body: str) -> str:
    found = re.search(r'<div class="note[^"]*">(.*?)</div>', body, re.S)
    return (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", found.group(1))).strip()
        if found
        else ""
    )


# -- routing ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/index.html", "/credentials", "/permissions"])
def test_every_page_answers(browser: Browser, path: str) -> None:
    status, body, _ = browser.get(path)

    assert status == 200
    assert "<html" in body


def test_an_unknown_address_is_a_404(browser: Browser) -> None:
    assert browser.get("/nope")[0] == 404
    # Checked before the guards are, so no token is needed to be told this.
    assert browser.post("/nope", {}, csrf=None)[0] == 404


def test_a_session_cookie_is_issued_once(browser: Browser) -> None:
    _, _, headers = browser.get("/")
    assert "SameSite=Strict" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]

    assert "Set-Cookie" not in browser.get("/")[2]


# -- the guards -------------------------------------------------------------


def test_a_post_from_another_site_is_refused(browser: Browser) -> None:
    """The pages rewrite credentials and permissions, so this matters."""
    status, body, _ = browser.post("/permissions", {"action": "save"}, origin=False)

    assert status == 403
    assert "Origin" in body


def test_a_wrong_token_is_refused(browser: Browser) -> None:
    status, body, _ = browser.post("/permissions", {"action": "save"}, csrf="nope")

    assert status == 403
    assert "Sicherheitstoken" in body


def test_a_missing_token_is_refused(browser: Browser) -> None:
    assert browser.post("/permissions", {"action": "save"}, csrf=None)[0] == 403


def test_a_client_without_a_cookie_cannot_act(installation: Installation) -> None:
    """The token has to be echoed back, so a first-contact POST cannot pass."""
    server = ConfigServer(("127.0.0.1", 0), Handler)
    server.installation = installation
    # A short poll interval only so that shutdown() returns promptly: the
    # default half second would be spent in the teardown of every test here.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        naive = Browser(f"http://127.0.0.1:{server.server_address[1]}")
        stolen = naive.token()
        naive.jar.clear()
        assert naive.post("/permissions", {"action": "save"}, csrf=stolen)[0] == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- permissions ------------------------------------------------------------


def flags(installation: Installation) -> dict[str, bool]:
    return json.loads(installation.settings.policy_file().read_text(encoding="utf-8"))


def test_saving_writes_a_complete_file(
    browser: Browser, installation: Installation
) -> None:
    status, body, _ = browser.post(
        "/permissions", {"action": "save", "tool": ["get_profile", "search_vouchers"]}
    )

    assert status == 200
    assert set(flags(installation)) == set(known_tools())
    assert flags(installation)["get_profile"] is True
    assert flags(installation)["create_voucher"] is False
    assert "2 von 25 Tools aktiv" in note(body)


def test_saving_a_writing_tool_says_so_by_name(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post(
        "/permissions", {"action": "save", "tool": ["create_voucher"]}
    )

    assert "create_voucher" in note(body)
    assert "Buchhaltungsdaten" in note(body)


def test_a_name_that_is_not_a_tool_is_ignored(
    browser: Browser, installation: Installation
) -> None:
    browser.post("/permissions", {"action": "save", "tool": ["made_up", "get_profile"]})

    assert "made_up" not in flags(installation)


def test_an_unknown_action_is_a_404(browser: Browser) -> None:
    assert browser.post("/permissions", {"action": "explode"})[0] == 404


# -- profiles ---------------------------------------------------------------


def test_a_profile_is_saved_from_the_current_selection(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post(
        "/permissions",
        {
            "action": "profile-save",
            "profile_name": "Nur Lesen",
            "tool": ["get_profile"],
        },
    )

    saved = installation.profiles.get("Nur Lesen")
    assert saved is not None and saved.tools == ("get_profile",)
    assert "Die Rechtedatei selbst ist unverändert" in note(body)
    assert not installation.settings.policy_file().exists()


def test_a_name_that_is_taken_is_refused_rather_than_overwritten(
    browser: Browser, installation: Installation
) -> None:
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    _, body, _ = browser.post(
        "/permissions",
        {
            "action": "profile-save",
            "profile_name": "nur   lesen",
            "tool": ["create_voucher"],
        },
    )

    assert "schon ein Profil" in note(body)
    assert "Nur Lesen" in note(body)
    assert " open>" in body  # the field to change the name is not folded away
    assert list(installation.profiles.all()) == ["Nur Lesen"]
    assert installation.profiles.all()["Nur Lesen"].tools == ("get_profile",)


def test_the_selected_profile_can_be_overwritten_on_purpose(
    browser: Browser, installation: Installation
) -> None:
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    _, body, _ = browser.post(
        "/permissions",
        {
            "action": "profile-overwrite",
            "profile": "Nur Lesen",
            "tool": ["create_voucher"],
        },
    )

    assert installation.profiles.all()["Nur Lesen"].tools == ("create_voucher",)
    assert "überschrieben" in note(body)
    assert not installation.settings.policy_file().exists()


def test_overwriting_a_profile_that_is_not_there(browser: Browser) -> None:
    _, body, _ = browser.post(
        "/permissions", {"action": "profile-overwrite", "profile": "weg"}
    )

    assert "Kein Profil" in note(body)


def test_a_profile_without_a_name_is_refused(browser: Browser) -> None:
    _, body, _ = browser.post(
        "/permissions", {"action": "profile-save", "profile_name": "  "}
    )

    assert "braucht einen Namen" in note(body)


def test_loading_a_profile_fills_the_form_but_writes_nothing(
    browser: Browser, installation: Installation
) -> None:
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())
    ToolPolicy(installation.settings.policy_file()).save(
        dict.fromkeys(known_tools(), True)
    )

    _, body, _ = browser.post(
        "/permissions", {"action": "load", "profile": "Nur Lesen"}
    )

    assert 'value="get_profile" id="get_profile" checked' in body
    assert 'value="create_voucher" id="create_voucher">' in body
    assert flags(installation)["create_voucher"] is True  # the file is untouched
    assert "Noch nichts geschrieben" in note(body)


def test_loading_a_profile_that_predates_a_tool_says_which(
    browser: Browser, installation: Installation
) -> None:
    installation.profiles.save("Alt", ["get_profile"], ["get_profile"])

    _, body, _ = browser.post("/permissions", {"action": "load", "profile": "Alt"})

    assert "neuer als das Profil" in note(body)
    assert "create_voucher" in note(body)


def test_loading_a_profile_that_is_not_there(browser: Browser) -> None:
    _, body, _ = browser.post("/permissions", {"action": "load", "profile": "weg"})

    assert "Kein Profil" in note(body)


def test_deleting_a_profile(browser: Browser, installation: Installation) -> None:
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    _, body, _ = browser.post(
        "/permissions", {"action": "profile-delete", "profile": "Nur Lesen"}
    )

    assert installation.profiles.all() == {}
    assert "gelöscht" in note(body)


# -- credentials ------------------------------------------------------------


def test_an_empty_key_changes_nothing(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post("/credentials", {"api_key": ""})

    assert "nichts geändert" in note(body)
    assert "LXO_MCP_API_KEY" not in installation.env_path.read_text(encoding="utf-8")


def test_a_key_is_verified_before_it_is_written(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post("/credentials", {"api_key": "a-new-key"})

    assert "Test Inc." in note(body)
    assert "LXO_MCP_API_KEY=a-new-key" in installation.env_path.read_text(
        encoding="utf-8"
    )


def test_a_key_the_api_rejects_is_not_written(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        probe, "check", lambda settings: (None, "Die API hat abgelehnt")
    )

    _, body, _ = browser.post("/credentials", {"api_key": "wrong"})

    assert "Nicht gespeichert" in note(body)
    assert "wrong" not in installation.env_path.read_text(encoding="utf-8")


def test_the_check_can_be_skipped(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a machine that is offline could never be configured."""
    monkeypatch.setattr(
        probe, "check", lambda settings: pytest.fail("must not ask the API")
    )

    _, body, _ = browser.post("/credentials", {"api_key": "offline", "unchecked": "1"})

    assert "Ungeprüft" in note(body)
    assert "LXO_MCP_API_KEY=offline" in installation.env_path.read_text(
        encoding="utf-8"
    )


def test_the_connection_test_reports_the_account(browser: Browser) -> None:
    _, body, _ = browser.post("/check", {})

    assert "Test Inc." in note(body)
    assert "Konto: Test Inc." in body  # and it stays in the chip


def test_a_failed_connection_test_says_why(
    browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "check", lambda settings: (None, "Kein API-Schlüssel"))

    _, body, _ = browser.post("/check", {})

    assert "Kein API-Schlüssel" in note(body)


# -- settings ---------------------------------------------------------------


def test_a_setting_is_written_and_takes_effect(
    browser: Browser, installation: Installation
) -> None:
    browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "80"})

    assert "LXO_MCP_PAGE_SIZE=80" in installation.env_path.read_text(encoding="utf-8")
    assert installation.settings.page_size == 80


def test_a_setting_the_server_would_refuse_is_not_written(
    browser: Browser, installation: Installation
) -> None:
    """Checked by the server's own code, so the two cannot disagree."""
    _, body, _ = browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "9999"})

    assert "würde das ablehnen" in note(body)
    assert "9999" not in installation.env_path.read_text(encoding="utf-8")


# -- carrying the policy file ----------------------------------------------


def test_the_transfer_page_is_gone(browser: Browser) -> None:
    """Settings and profiles do not travel. One policy file does."""
    assert browser.get("/transfer")[0] == 404
    assert browser.post("/transfer", {"action": "preview"}, csrf=None)[0] == 404


def test_the_export_is_the_policy_file_itself(
    browser: Browser, installation: Installation
) -> None:
    installation.env_path.write_text("LXO_MCP_API_KEY=secret-value", encoding="utf-8")
    ToolPolicy(installation.settings.policy_file()).save({"get_profile": True})

    status, body, headers = browser.get("/export")

    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    assert "secret-value" not in body
    assert json.loads(body) == flags(installation)


def test_the_export_button_downloads_the_same(
    browser: Browser, installation: Installation
) -> None:
    ToolPolicy(installation.settings.policy_file()).save({"get_profile": True})

    status, body, headers = browser.post("/permissions", {"action": "policy-export"})

    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    assert json.loads(body)["get_profile"] is True


def test_importing_fills_the_form_and_writes_nothing(
    browser: Browser, installation: Installation
) -> None:
    ToolPolicy(installation.settings.policy_file()).save(
        dict.fromkeys(known_tools(), True)
    )
    arriving = transfer.dumps({"get_profile": True, "create_voucher": False})

    _, body, _ = browser.post(
        "/permissions", {"action": "policy-import", "bundle": arriving}
    )

    assert 'value="get_profile" id="get_profile" checked' in body
    assert 'value="create_voucher" id="create_voucher">' in body
    assert flags(installation)["create_voucher"] is True  # the file is untouched
    assert "Geschrieben ist noch nichts" in note(body)


def test_a_tool_the_file_predates_stays_off_and_is_named(
    browser: Browser, installation: Installation
) -> None:
    """The rule `--tools sync` follows: silence is off, and it is said aloud."""
    arriving = transfer.dumps({"get_profile": True})

    _, body, _ = browser.post(
        "/permissions", {"action": "policy-import", "bundle": arriving}
    )

    assert 'value="create_voucher" id="create_voucher">' in body
    assert "nennt die Datei nicht" in note(body)
    assert "create_voucher" in note(body)
    assert "1 von 25 Tools angehakt" in note(body)


def test_a_name_that_is_no_longer_a_tool_is_reported_and_dropped(
    browser: Browser, installation: Installation
) -> None:
    arriving = transfer.dumps({"get_profile": True, "tool_from_an_older_version": True})

    _, body, _ = browser.post(
        "/permissions", {"action": "policy-import", "bundle": arriving}
    )

    assert "tool_from_an_older_version" in note(body)
    assert "hier nicht gibt" in note(body)
    assert "tool_from_an_older_version" not in body.split("<form")[1].split("</form>")[
        0
    ].replace(note(body), "")


def test_a_file_that_is_not_a_policy_is_refused(browser: Browser) -> None:
    _, body, _ = browser.post(
        "/permissions", {"action": "policy-import", "bundle": "kaputt"}
    )

    assert "keine gültige JSON" in note(body)


def test_a_refused_import_keeps_the_ticks_that_were_set(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post(
        "/permissions",
        {"action": "policy-import", "bundle": "kaputt", "tool": ["create_voucher"]},
    )

    assert 'value="create_voucher" id="create_voucher" checked' in body
    assert not installation.settings.policy_file().exists()


def test_an_imported_file_becomes_the_policy_once_it_is_saved(
    browser: Browser, installation: Installation
) -> None:
    """The round trip a person actually makes: read a file, then save."""
    arriving = transfer.dumps({"get_profile": True, "search_vouchers": True})

    browser.post("/permissions", {"action": "policy-import", "bundle": arriving})
    browser.post(
        "/permissions",
        {"action": "save", "tool": ["get_profile", "search_vouchers"]},
    )

    assert transfer.parse(
        installation.settings.policy_file().read_text(encoding="utf-8")
    ) == {name: name in ("get_profile", "search_vouchers") for name in known_tools()}


# -- the HTTP token ---------------------------------------------------------


def test_the_token_can_be_saved_from_the_page(
    browser: Browser, installation: Installation
) -> None:
    status, body, _ = browser.post(
        "/bearer", {"bearer": "a-token-typed-by-hand", "action": "save"}
    )

    assert status == 200
    written = read_env_file(installation.env_path)
    assert written["LXO_MCP_BEARER_TOKEN"] == "a-token-typed-by-hand"
    assert "gespeichert" in note(body)


def test_generating_writes_a_long_random_token(
    browser: Browser, installation: Installation
) -> None:
    _, body, _ = browser.post("/bearer", {"action": "generate"})
    first = read_env_file(installation.env_path)["LXO_MCP_BEARER_TOKEN"]

    assert len(first) >= 32
    assert "erzeugt" in note(body)

    browser.post("/bearer", {"action": "generate"})
    assert read_env_file(installation.env_path)["LXO_MCP_BEARER_TOKEN"] != first


def test_an_empty_token_is_refused(
    browser: Browser, installation: Installation
) -> None:
    """Blank means cleared here, not unchanged: the field shows what is set."""
    browser.post("/bearer", {"bearer": "the-one-in-force", "action": "save"})

    _, body, _ = browser.post("/bearer", {"bearer": "   ", "action": "save"})

    still = read_env_file(installation.env_path)["LXO_MCP_BEARER_TOKEN"]
    assert still == "the-one-in-force"
    assert "Nicht gespeichert" in note(body)


def test_the_page_shows_the_token_it_would_hand_to_a_client(
    browser: Browser,
) -> None:
    """Unlike the API key, which is never shown back: this one gets copied."""
    browser.post("/bearer", {"bearer": "shown-because-it-is-copied", "action": "save"})

    _, body, _ = browser.get("/credentials")

    assert "shown-because-it-is-copied" in body
