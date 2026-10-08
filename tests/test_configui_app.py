"""The local server: routing, the two guards, and what each action writes.

A real ``ThreadingHTTPServer`` on a loopback port, driven through a real
cookie jar. Nothing here reaches the API — ``probe.check`` is replaced, which
is the only function in the interface that would.
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from benethos_lexware_office_mcp.configui import probe, transfer
from benethos_lexware_office_mcp.configui.app import ConfigServer, Handler, serve
from benethos_lexware_office_mcp.configui.profiles import ProfileStore
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools
from benethos_lexware_office_mcp.settings import DEFAULT_PAGE_SIZE, Settings, envfile
from benethos_lexware_office_mcp.settings.envfile import read_env_file

ACCOUNT = probe.Account(company="Test Inc.", tax_type="net")


def fake_check(settings: Settings, *, keep: bool = True) -> tuple[probe.Account, str]:
    """Stands in for the one function here that would reach the API.

    It remembers the account the way the real one does, because the chip on
    every page is drawn from that memory.
    """
    if keep:
        probe.remember(ACCOUNT)
    return ACCOUNT, "Verbindung steht."


class Stay(urllib.request.HTTPRedirectHandler):
    """Answers a redirect with the redirect itself, rather than following it."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Browser:
    """Just enough of one: a cookie jar, forms, and the CSRF token.

    It follows a redirect as a browser does, unless ``follow`` says not to.
    """

    # The server it talks to, for a test about the start code.
    server: ConfigServer

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.staying = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), Stay()
        )

    def get(self, path: str) -> tuple[int, str, dict[str, str]]:
        return self._open(urllib.request.Request(self.base + path))

    def token(self) -> str:
        """Any page with a form carries it: it is the session cookie, echoed back."""
        _, body, _ = self.get("/credentials")
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
        follow: bool = True,
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
        return self._open(request, follow=follow)

    def _open(
        self, request: urllib.request.Request, *, follow: bool = True
    ) -> tuple[int, str, dict[str, str]]:
        opener = self.opener if follow else self.staying
        try:
            with opener.open(request) as response:
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
        browser = Browser(f"http://127.0.0.1:{server.server_address[1]}")
        # Signed in the way the address the start prints signs one in.
        browser.get(f"/?code={server.code}")
        browser.server = server
        yield browser
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def note(body: str) -> str:
    found = re.search(r'<div class="notice[^"]*" role="[^"]*">(.*?)</div>', body, re.S)
    return (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", found.group(1))).strip()
        if found
        else ""
    )


# -- routing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/index.html", "/credentials", "/permissions", "/settings"]
)
def test_every_page_answers(browser: Browser, path: str) -> None:
    status, body, _ = browser.get(path)

    assert status == 200
    assert "<html" in body


def test_an_env_file_in_another_encoding_is_said_on_the_page(
    browser: Browser, installation: Installation
) -> None:
    """Every page reads the .env. A request thread ending in a traceback
    left the browser with nothing, on the interface meant to repair it."""
    token = browser.token()  # while a page still renders
    original = "LXO_MCP_DOWNLOAD_DIR=C:/Jürgen\n".encode("cp1252")
    installation.env_path.write_bytes(original)

    status, body, _ = browser.get("/")
    assert status == 500
    assert "not UTF-8" in body
    assert "not UTF-8" in browser.get("/credentials")[1]

    status, body, _ = browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "20"}, csrf=token)
    assert "not UTF-8" in body
    assert installation.env_path.read_bytes() == original


def test_an_unknown_address_is_a_404(browser: Browser) -> None:
    assert browser.get("/nope")[0] == 404
    # Checked before the guards are, so no token is needed to be told this.
    assert browser.post("/nope", {}, csrf=None)[0] == 404


def test_a_session_cookie_is_issued_once(browser: Browser) -> None:
    newcomer = Browser(browser.base)

    _, _, headers = newcomer.get("/")
    assert "SameSite=Strict" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]

    assert "Set-Cookie" not in newcomer.get("/")[2]


# -- the start code ---------------------------------------------------------


def test_without_the_code_every_page_asks_for_it(browser: Browser) -> None:
    stranger = Browser(browser.base)

    for path in ("/", "/credentials", "/permissions", "/settings", "/export"):
        status, body, _ = stranger.get(path)
        assert status == 403, path
        assert "<h2>Code eingeben</h2>" in body, path
        assert 'name="code"' in body, path
    # What a page needs to look like one is not behind it.
    assert stranger.get("/static/app.css")[0] == 200


def test_the_code_in_the_address_signs_in_and_leaves_the_address(
    browser: Browser,
) -> None:
    stranger = Browser(browser.base)

    status, _, headers = stranger._open(
        urllib.request.Request(
            f"{browser.base}/permissions?code={browser.server.code}"
        ),
        follow=False,
    )

    assert status == 303
    assert headers["Location"] == "/permissions"
    assert stranger.get("/permissions")[0] == 200


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_a_code_in_an_address_another_page_opened_is_not_tried(
    browser: Browser, site: str
) -> None:
    """A page elsewhere could load the address in a loop, unseen, and each
    wrong code it sent counted, and waited, for the person's own too.

    ``same-site`` is another port on the same loopback name.
    """
    stranger = Browser(browser.base)
    request = urllib.request.Request(f"{browser.base}/?code={browser.server.code}")
    request.add_header("Sec-Fetch-Site", site)

    status, body, _ = stranger._open(request)

    assert status == 403
    assert "<h2>Code eingeben</h2>" in body
    assert stranger.get("/")[0] == 403


def test_a_code_in_an_address_typed_or_opened_by_setup_is_tried(
    browser: Browser,
) -> None:
    """What a browser sends for an address typed, pasted or handed to it."""
    stranger = Browser(browser.base)
    request = urllib.request.Request(f"{browser.base}/?code={browser.server.code}")
    request.add_header("Sec-Fetch-Site", "none")

    stranger._open(request)

    assert stranger.get("/")[0] == 200


def test_the_code_typed_into_the_field_signs_in(browser: Browser) -> None:
    stranger = Browser(browser.base)

    status, _, headers = stranger.post(
        "/code", {"code": f" {browser.server.code} "}, follow=False
    )

    assert status == 303
    assert headers["Location"] == "/"
    assert stranger.get("/settings")[0] == 200


def test_a_wrong_code_is_refused_and_signs_nothing_in(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    stranger = Browser(browser.base)

    status, body, _ = stranger.post("/code", {"code": "guessed"})

    assert status == 403
    assert "passt nicht" in note(body)
    assert stranger.get("/")[0] == 403
    assert "Request refused by the code check" in lines.text
    assert browser.server.code not in lines.text


def test_a_form_without_the_sign_in_writes_nothing(
    browser: Browser, installation: Installation
) -> None:
    """Origin and token in order, the code missing: still nothing written."""
    stranger = Browser(browser.base)

    status, _, _ = stranger.post("/permissions", {"action": "save", "tool": []})

    assert status == 403
    assert not installation.policy_path.exists()


def test_after_five_wrong_codes_each_waits(browser: Browser) -> None:
    waited: list[float] = []
    browser.server.pause = waited.append
    stranger = Browser(browser.base)

    for _ in range(5):
        stranger.post("/code", {"code": "guessed"})
    assert waited == []

    stranger.post("/code", {"code": "guessed"})
    stranger.get(f"/?code={browser.server.code}")
    assert waited == [2.0]  # the right one did not wait

    stranger.post("/code", {"code": "guessed"})
    assert waited == [2.0]  # and it started the count over


def test_a_right_code_is_not_held_behind_a_waiting_wrong_one(
    browser: Browser,
) -> None:
    """Whatever loops wrong codes must not keep the person out."""
    server = browser.server
    paused, release = threading.Event(), threading.Event()

    def pause(seconds: float) -> None:
        paused.set()
        release.wait(10)

    server.pause = pause
    for _ in range(5):
        server.try_code("loop", "guessed")
    waiting = threading.Thread(target=server.try_code, args=("loop", "guessed"))
    waiting.start()
    assert paused.wait(5)
    signed_in = threading.Event()

    def person() -> None:
        if server.try_code("person", server.code):
            signed_in.set()

    threading.Thread(target=person, daemon=True).start()
    try:
        assert signed_in.wait(2)
    finally:
        release.set()
        waiting.join(timeout=5)


def test_a_sign_in_is_a_line_and_the_code_is_not(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    Browser(browser.base).get(f"/?code={browser.server.code}")

    assert "A browser signed in with the start code" in lines.text
    assert browser.server.code not in lines.text


def test_the_start_prints_the_address_with_the_code(
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    lines: pytest.LogCaptureFixture,
) -> None:
    """The line a person copies, from a terminal or from a container's log.

    At WARNING, so a log level set higher than INFO cannot hide it.
    """
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr(ConfigServer, "serve_forever", lambda self: None)

    serve(installation, port=0, open_browser=True)

    (record,) = [r for r in lines.records if "interface at" in r.getMessage()]
    assert record.levelno == logging.WARNING
    found = re.search(r"(http://127\.0\.0\.1:\d+/\?code=\S+)", record.getMessage())
    assert found
    assert opened == [found.group(1)]
    for kind in ("settings", "policy", "profiles"):
        assert f"Editing the {kind} file" in lines.text


# -- Post/Redirect/Get ------------------------------------------------------


def test_a_form_that_went_through_redirects_and_says_so_once(
    browser: Browser,
) -> None:
    """A reload of the next page repeats nothing, and says nothing twice."""
    status, body, headers = browser.post(
        "/permissions", {"action": "save", "tool": ["get_profile"]}, follow=False
    )

    assert status == 303
    assert headers["Location"] == "/permissions"
    assert body == ""
    assert "1 von 25 Tools aktiv" in note(browser.get("/permissions")[1])
    assert note(browser.get("/permissions")[1]) == ""


def test_the_message_is_for_the_session_that_sent_the_form(
    browser: Browser,
) -> None:
    browser.post("/permissions", {"action": "save", "tool": []}, follow=False)
    stranger = Browser(browser.base)

    assert note(stranger.get("/permissions")[1]) == ""
    assert "0 von 25 Tools aktiv" in note(browser.get("/permissions")[1])


def test_the_message_waits_for_the_next_page_whichever_it_is(
    browser: Browser,
) -> None:
    """The ticks of a loaded profile belong to its page, the message not."""
    browser.post("/permissions", {"action": "save", "tool": []}, follow=False)

    assert "0 von 25 Tools aktiv" in note(browser.get("/credentials")[1])


def test_a_refused_form_comes_back_at_once_with_what_was_typed(
    browser: Browser, installation: Installation
) -> None:
    status, body, _ = browser.post(
        "/settings",
        {"LXO_MCP_PAGE_SIZE": "9999", "LXO_MCP_TIMEOUT": "20"},
        follow=False,
    )

    assert status == 400
    assert "würde das ablehnen" in note(body)
    assert 'name="LXO_MCP_PAGE_SIZE" type="text" value="9999"' in body
    assert 'name="LXO_MCP_TIMEOUT" type="text" value="20"' in body
    assert "9999" not in installation.env_path.read_text(encoding="utf-8")


def test_a_refused_key_is_not_shown_again(
    browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        probe, "check", lambda settings, **_: (None, "Die API hat abgelehnt")
    )

    status, body, _ = browser.post("/credentials", {"api_key": "typed-but-wrong"})

    assert status == 400
    assert "typed-but-wrong" not in body


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


def test_a_token_with_a_non_ascii_character_is_refused_too(browser: Browser) -> None:
    """`compare_digest` raises on such a string rather than answering False.

    With a session cookie in place, or the check ends before comparing.
    """
    browser.token()
    status, body, _ = browser.post("/permissions", {"action": "save"}, csrf="nöpe")

    assert status == 403
    assert "Sicherheitstoken" in body


@pytest.mark.parametrize("host", ["attacker.example:8770", "192.168.1.20:8770", ""])
def test_a_page_addressed_by_another_name_is_refused(
    browser: Browser, host: str
) -> None:
    """DNS rebinding: a foreign name pointed at 127.0.0.1 reads as its own
    origin, so the name the browser used has to be a loopback one."""
    request = urllib.request.Request(browser.base + "/credentials")
    request.add_header("Host", host)

    status, body, _ = browser._open(request)

    assert status == 403
    assert "127.0.0.1" in body


def test_a_refusal_shows_nothing_of_the_interface(browser: Browser) -> None:
    """A page refused for its name is answered before any sign-in, to a
    rebinding page among others. The frame of the pages names the account
    and offers Beenden."""
    probe.remember(ACCOUNT)
    request = urllib.request.Request(browser.base + "/credentials")
    request.add_header("Host", "attacker.example:8771")

    status, body, _ = browser._open(request)

    assert status == 403
    assert "Test Inc." not in body
    assert "/shutdown" not in body


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1:9999", "[::1]:8771"])
def test_any_loopback_name_and_port_is_answered(browser: Browser, host: str) -> None:
    """A container publishes under a port of its own choosing."""
    request = urllib.request.Request(browser.base + "/")
    request.add_header("Host", host)

    assert browser._open(request)[0] == 200


def test_no_page_is_cached(browser: Browser) -> None:
    """They show the bearer token and name the company."""
    assert browser.get("/credentials")[2]["Cache-Control"] == "no-store"
    assert browser.get("/export")[2]["Cache-Control"] == "no-store"


def test_no_page_can_be_framed_or_sniffed(browser: Browser) -> None:
    headers = browser.get("/permissions")[2]

    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize("length", ["999999999999", "-5", "many"])
def test_an_oversized_or_nonsense_body_is_refused_unread(
    browser: Browser, length: str
) -> None:
    """Reading what a Content-Length claims would be the whole attack."""
    host, port = browser.base.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(
            f"POST /permissions HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Content-Length: {length}\r\n\r\n".encode()
        )
        # Read to the end, so the server is not left writing into a socket
        # this side already closed.
        received = b""
        while chunk := sock.recv(4096):
            received += chunk
        answer = received.decode("latin-1")

    assert answer.startswith("HTTP/1.0 413") or answer.startswith("HTTP/1.1 413")


def test_a_page_on_another_loopback_port_is_refused(browser: Browser) -> None:
    """Loopback is not enough: any local program serves from loopback."""
    port = int(browser.base.rsplit(":", 1)[1])
    token = browser.token()
    request = urllib.request.Request(
        browser.base + "/permissions",
        data=urlencode({"action": "save", "_csrf": token}).encode("utf-8"),
    )
    request.add_header("Origin", f"http://127.0.0.1:{port + 1}")

    status, body, _ = browser._open(request)

    assert status == 403
    assert "Origin" in body


def test_a_planted_cookie_is_not_a_session(browser: Browser) -> None:
    """Cookies ignore the port, so another local page can set this one.

    The value it picks then appears both as the cookie and in the form, and
    the two match - which is why matching is not enough on its own.
    """
    planted = "chosen-by-another-page"
    request = urllib.request.Request(
        browser.base + "/permissions",
        data=urlencode({"action": "save", "_csrf": planted}).encode("utf-8"),
    )
    request.add_header("Origin", browser.base)
    request.add_header("Cookie", f"lxo_config={planted}")

    status, body, _ = browser._open(request)

    assert status == 403
    assert "Sicherheitstoken" in body


@pytest.mark.parametrize(
    "header",
    [
        "other=a b; lxo_config={session}",
        'lxo_config={session}; other="unclosed',
        "lxo_config=planted-by-another-page; lxo_config={session}",
        "lxo_config={session}; lxo_config=planted-by-another-page",
    ],
)
def test_another_programs_cookie_does_not_end_the_session(
    browser: Browser, header: str
) -> None:
    """Cookies ignore the port, so other programs on the same loopback name
    add theirs to this header. One the cookie parser found illegal made it
    drop the whole header, and the session with it, for good."""
    (cookie,) = [c for c in browser.jar if c.name == "lxo_config"]
    request = urllib.request.Request(browser.base + "/settings")
    request.add_header("Cookie", header.format(session=cookie.value))

    status, _, headers = browser._open(request)

    assert status == 200
    assert "Set-Cookie" not in headers


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


def test_a_key_that_could_not_be_written_does_not_name_its_account(
    browser: Browser, installation: Installation
) -> None:
    """The chip says whose records the permissions are about. A key that
    was checked and then not saved is not this installation's key."""
    installation.env_path.unlink()
    installation.env_path.mkdir()

    _, body, _ = browser.post("/credentials", {"api_key": "a-new-key"})

    assert "nicht schreiben" in note(body)
    assert probe.last_account() is None
    assert "Test Inc." not in browser.get("/permissions")[1]


def test_a_key_the_api_rejects_is_not_written(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        probe, "check", lambda settings, **_: (None, "Die API hat abgelehnt")
    )

    _, body, _ = browser.post("/credentials", {"api_key": "wrong"})

    assert "Nicht gespeichert" in note(body)
    assert "wrong" not in installation.env_path.read_text(encoding="utf-8")


def test_the_check_can_be_skipped(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a machine that is offline could never be configured."""
    monkeypatch.setattr(
        probe, "check", lambda settings, **_: pytest.fail("must not ask the API")
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
    monkeypatch.setattr(
        probe, "check", lambda settings, **_: (None, "Kein API-Schlüssel")
    )

    _, body, _ = browser.post("/check", {})

    assert "Kein API-Schlüssel" in note(body)


# -- settings ---------------------------------------------------------------


def test_a_setting_is_written_and_takes_effect(
    browser: Browser, installation: Installation
) -> None:
    browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "80"})

    assert "LXO_MCP_PAGE_SIZE=80" in installation.env_path.read_text(encoding="utf-8")
    assert installation.settings.page_size == 80


def test_an_emptied_setting_falls_back_to_the_default(
    browser: Browser, installation: Installation
) -> None:
    """The page says empty means the default. The empty field used to be
    dropped before the action saw it, the old value stayed, and the page
    reported success."""
    browser.post("/settings", {"LXO_MCP_PAGE_SIZE": ""})

    assert read_env_file(installation.env_path)["LXO_MCP_PAGE_SIZE"] == ""
    assert installation.settings.page_size == DEFAULT_PAGE_SIZE


def test_an_unknown_log_level_is_refused_rather_than_stored(
    browser: Browser, installation: Installation
) -> None:
    """The server falls back to INFO for it, so stored it never took effect."""
    _, body, _ = browser.post("/settings", {"LXO_MCP_LOG_LEVEL": "verbose"})

    assert "Nicht gespeichert" in note(body)
    assert "verbose" not in installation.env_path.read_text(encoding="utf-8")

    browser.post("/settings", {"LXO_MCP_LOG_LEVEL": "debug"})
    assert installation.settings.log_level == "DEBUG"


def test_two_saves_at_once_both_arrive(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every request has a thread. Each save reads the file, changes it and
    writes it back, so two at once each wrote what they had read."""
    real_read = envfile._existing_lines

    def slow_read(path: Path) -> list[str]:
        seen = real_read(path)
        time.sleep(0.2)  # long enough for the other save to read the same
        return seen

    monkeypatch.setattr(envfile, "_existing_lines", slow_read)
    token = browser.token()
    saves = [
        threading.Thread(
            target=browser.post,
            args=("/settings", {key: value}),
            kwargs={"csrf": token},
        )
        for key, value in (("LXO_MCP_PAGE_SIZE", "80"), ("LXO_MCP_TIMEOUT", "20"))
    ]
    for save in saves:
        save.start()
    for save in saves:
        save.join(timeout=10)

    written = read_env_file(installation.env_path)
    assert written["LXO_MCP_PAGE_SIZE"] == "80"
    assert written["LXO_MCP_TIMEOUT"] == "20"


def test_a_blank_field_the_file_does_not_carry_is_not_written(
    browser: Browser, installation: Installation
) -> None:
    """The form sends every field. Nothing to clear means nothing to write."""
    browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "80", "LXO_MCP_TIMEOUT": ""})

    assert "LXO_MCP_TIMEOUT" not in installation.env_path.read_text(encoding="utf-8")


def test_a_setting_the_server_would_refuse_is_not_written(
    browser: Browser, installation: Installation
) -> None:
    """Checked by the server's own code, so the two cannot disagree."""
    _, body, _ = browser.post("/settings", {"LXO_MCP_PAGE_SIZE": "9999"})

    assert "würde das ablehnen" in note(body)
    assert "9999" not in installation.env_path.read_text(encoding="utf-8")


def test_a_value_cannot_smuggle_in_a_second_setting(
    browser: Browser, installation: Installation
) -> None:
    """%0A in a form field used to end the line and write a key of its own."""
    _, body, _ = browser.post(
        "/settings",
        {"LXO_MCP_DOWNLOAD_DIR": "downloads\nLXO_MCP_API_KEY=planted"},
    )

    assert "Nicht gespeichert" in note(body)
    assert "planted" not in installation.env_path.read_text(encoding="utf-8")


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


# -- when a file cannot be written -----------------------------------------


def test_a_policy_file_that_cannot_be_written_is_reported(
    browser: Browser, installation: Installation
) -> None:
    """A directory where the file should be: the OS refuses, the page says so."""
    installation.policy_path.mkdir()

    _, body, _ = browser.post(
        "/permissions", {"action": "save", "tool": ["get_profile"]}
    )

    assert "Konnte" in note(body) and "nicht schreiben" in note(body)
    assert str(installation.policy_path) in note(body)


def test_a_profile_file_that_cannot_be_written_is_reported(
    browser: Browser, installation: Installation
) -> None:
    installation.profiles.path.mkdir()

    _, body, _ = browser.post(
        "/permissions",
        {"action": "profile-save", "profile_name": "Neu", "tool": ["get_profile"]},
    )

    assert "Konnte" in note(body) and "nicht schreiben" in note(body)
    assert " open>" in body  # the profile block stays open beside the message


def test_an_overwrite_that_cannot_be_written_is_reported(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The profile is found, so the failure is the write itself."""
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    def refused(self: ProfileStore, *args: object) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(ProfileStore, "save", refused)

    _, body, _ = browser.post(
        "/permissions",
        {"action": "profile-overwrite", "profile": "Nur Lesen", "tool": []},
    )

    assert "nicht schreiben: Permission denied" in note(body)
    assert installation.profiles.all()["Nur Lesen"].tools == ("get_profile",)


def test_a_delete_that_cannot_be_written_is_reported(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It used to escape the handler, and the browser got a dropped connection."""
    installation.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    def refused(self: ProfileStore, *args: object) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(ProfileStore, "delete", refused)

    status, body, _ = browser.post(
        "/permissions", {"action": "profile-delete", "profile": "Nur Lesen"}
    )

    assert status == 500
    assert "nicht schreiben: Permission denied" in note(body)


# -- what reaches stderr ----------------------------------------------------


def test_a_saved_key_is_a_line_and_the_key_is_not(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    browser.post("/credentials", {"api_key": "a-new-key-0123456789"})

    assert "API key written to .env, checked against the account first" in lines.text
    assert "a-new-key" not in lines.text


def test_a_key_the_account_refused_is_a_warning(
    browser: Browser, lines: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "check", lambda settings, **_: (None, "abgelehnt"))

    browser.post("/credentials", {"api_key": "wrong-key-0123456789"})

    assert "API key not saved: the account refused it" in lines.text
    assert "wrong-key" not in lines.text


def test_a_generated_token_is_a_line_and_the_token_is_not(
    browser: Browser, installation: Installation, lines: pytest.LogCaptureFixture
) -> None:
    browser.post("/bearer", {"action": "generate"})

    token = read_env_file(installation.env_path)["LXO_MCP_BEARER_TOKEN"]
    assert "Bearer token generated and written to .env" in lines.text
    assert token not in lines.text


def test_a_setting_is_named_and_its_value_is_not(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    browser.post("/settings", {"LXO_MCP_APP_BASE_URL": "https://app.example.test"})

    assert "1 setting written to .env: LXO_MCP_APP_BASE_URL" in lines.text
    assert "example.test" not in lines.text


def test_switching_on_a_writing_tool_is_a_warning_that_names_it(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    browser.post("/permissions", {"action": "save", "tool": ["create_contact"]})

    (record,) = [r for r in lines.records if "Tool policy" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "1 of them able to change real accounting records: create_contact" in (
        record.getMessage()
    )


def test_a_profile_created_and_deleted_leaves_two_lines(
    browser: Browser, lines: pytest.LogCaptureFixture
) -> None:
    browser.post(
        "/permissions",
        {
            "action": "profile-save",
            "profile_name": "Nur Lesen",
            "tool": ["get_profile"],
        },
    )
    browser.post("/permissions", {"action": "profile-delete", "profile": "Nur Lesen"})

    assert "Profile 'Nur Lesen' created with 1 tool" in lines.text
    assert "Profile 'Nur Lesen' deleted" in lines.text


@pytest.mark.parametrize(
    ("check", "post"),
    [
        ("origin", {"origin": False}),
        ("token", {"csrf": "nope"}),
    ],
)
def test_a_refused_post_says_which_check_refused_it(
    browser: Browser,
    lines: pytest.LogCaptureFixture,
    check: str,
    post: dict[str, Any],
) -> None:
    browser.post("/permissions", {"action": "save"}, **post)

    assert f"Request refused by the {check} check" in lines.text


def test_a_write_that_failed_is_a_warning(
    browser: Browser, installation: Installation, lines: pytest.LogCaptureFixture
) -> None:
    installation.policy_path.mkdir()

    browser.post("/permissions", {"action": "save", "tool": ["get_profile"]})

    assert f"Could not write {installation.policy_path}:" in lines.text


def test_a_second_interface_cannot_take_a_port_already_served() -> None:
    """On Windows SO_REUSEADDR let it, and the first one kept the browser."""
    first = ConfigServer(("127.0.0.1", 0), Handler)
    try:
        with pytest.raises(OSError):
            ConfigServer(("127.0.0.1", first.server_address[1]), Handler)
    finally:
        first.server_close()


def test_a_taken_port_is_one_line_and_no_traceback(
    installation: Installation, lines: pytest.LogCaptureFixture
) -> None:
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    try:
        with pytest.raises(SystemExit) as ended:
            serve(installation, port=taken.getsockname()[1], open_browser=False)
    finally:
        taken.close()

    assert ended.value.code == 1
    (record,) = [r for r in lines.records if "Could not open" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert "--port" in record.getMessage()
    assert "Traceback" not in lines.text


@pytest.mark.parametrize(
    ("path", "form"),
    [
        ("/credentials", {"api_key": "a-new-key", "unchecked": "1"}),
        ("/bearer", {"action": "generate"}),
    ],
)
def test_a_save_beside_a_broken_setting_says_it_was_written(
    browser: Browser, installation: Installation, path: str, form: dict[str, str]
) -> None:
    """The file already held a value the server refuses, which is not this save's.

    The write succeeds, and reading the settings back afterwards fails on the
    other value. The page says both.
    """
    installation.env_path.write_text("LXO_MCP_PAGE_SIZE=many\n", encoding="utf-8")

    status, body, _ = browser.post(path, form)

    assert status == 200
    assert "LXO_MCP_PAGE_SIZE" in note(body)
    assert re.search("geschrieben|gespeichert", note(body))


def test_a_key_no_header_can_carry_is_refused_before_it_is_tried(
    browser: Browser, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero-width space pasted along: encoding it failed inside the check."""
    monkeypatch.setattr(
        probe, "check", lambda settings, **_: pytest.fail("must not ask the API")
    )

    status, body, _ = browser.post("/credentials", {"api_key": "a-new​key"})

    assert status == 400
    assert "Nicht gespeichert" in note(body)
    assert "a-new" not in installation.env_path.read_text(encoding="utf-8")


def test_saved_settings_land_back_on_their_page(browser: Browser) -> None:
    status, _, headers = browser.post(
        "/settings", {"LXO_MCP_PAGE_SIZE": "80"}, follow=False
    )

    assert status == 303
    assert headers["Location"] == "/settings"


def test_a_connection_test_lands_on_the_credentials_page(browser: Browser) -> None:
    status, _, headers = browser.post("/check", {}, follow=False)

    assert status == 303
    assert headers["Location"] == "/credentials"


# -- ending it from the page ------------------------------------------------


def test_beenden_answers_and_then_ends_the_process(browser: Browser) -> None:
    browser.server.linger = 0
    stopped = threading.Event()
    real = browser.server.stop_after_actions

    def stop() -> None:
        real()
        stopped.set()

    browser.server.stop_after_actions = stop  # type: ignore[method-assign]

    status, body, _ = browser.post("/shutdown", {})

    assert status == 200
    assert "<h2>Beendet</h2>" in body
    assert stopped.wait(5)


def test_beenden_needs_the_start_code(browser: Browser) -> None:
    stranger = Browser(browser.base)

    status, _, _ = stranger.post("/shutdown", {})

    assert status == 403
    assert not browser.server.stopped_from_page
    assert browser.get("/")[0] == 200


def test_beenden_needs_the_token(browser: Browser) -> None:
    assert browser.post("/shutdown", {}, csrf="nope")[0] == 403
    assert not browser.server.stopped_from_page


def test_while_ending_no_form_is_acted_on(
    browser: Browser, installation: Installation
) -> None:
    """The second it lingers is for the stylesheet, not for another save."""
    browser.server.linger = 60  # the timer is a daemon, the test ends first
    browser.post("/shutdown", {})

    status, _, _ = browser.post("/permissions", {"action": "save", "tool": []})

    assert status == 503
    assert not installation.policy_path.exists()


def test_every_page_offers_beenden_with_a_question(browser: Browser) -> None:
    for path in ("/", "/credentials", "/permissions", "/settings"):
        body = browser.get(path)[1]
        form = re.search(r'<form[^>]*action="/shutdown"[^>]*>', body)
        assert form and "data-confirm=" in form.group(0), path


def test_ended_from_the_page_is_said_on_stderr(
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    lines: pytest.LogCaptureFixture,
) -> None:
    def served_until_beenden(self: ConfigServer) -> None:
        self.stopped_from_page = True

    monkeypatch.setattr(ConfigServer, "serve_forever", served_until_beenden)

    serve(installation, port=0, open_browser=False)

    assert "Stopped from the page" in lines.text


def test_ctrl_c_is_a_line_rather_than_a_traceback(
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    lines: pytest.LogCaptureFixture,
) -> None:
    def interrupted(self: ConfigServer) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ConfigServer, "serve_forever", interrupted)

    serve(installation, port=0, open_browser=False)

    assert "Stopped by an interrupt" in lines.text
