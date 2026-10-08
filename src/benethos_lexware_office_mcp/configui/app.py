"""The local web server that puts the three pages in a browser.

**Never part of the MCP server.** That one speaks JSON-RPC over stdio and must
keep stdout to itself. This is a separate command, started by a person, that
serves on the loopback interface and stops when they are done. The two share
their configuration modules and nothing else.

**It binds 127.0.0.1 unless told otherwise.** The pages have no login,
because a page only the local machine can reach does not need one. A
container is the case that has to say otherwise: a process bound to the
container's own loopback cannot be reached through a published port at all.
There the isolation is the network namespace and the host-side publish, not
the bind address. Anywhere else, changing it is a decision with consequences,
and the server says so on stderr when it does.

State-changing requests are guarded twice, because they rewrite credentials
and permissions and a page in another tab must not be able to trigger one:
the ``Origin`` or ``Referer`` has to be this very page, loopback host and port
both, and a random token from a ``SameSite=Strict`` cookie has to come back in
the form - a token this process issued, not merely one the cookie carries.

What a request that passes both then does is :mod:`.actions`. This module is
the HTTP around it: sessions, headers, the guards and the routing.
"""

from __future__ import annotations

import secrets
import sys
import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__, logbook
from ..errors import ConfigError
from ..settings import LOOPBACK_NAMES
from . import actions, pages
from .actions import Form, Reply, field
from .render import esc, page
from .state import Installation

__all__ = ["ConfigServer", "Handler", "serve"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

_SESSION_COOKIE = "lxo_config"

# The largest form this interface accepts. An imported policy file is the
# biggest thing any of them carries, and that is a few kilobytes.
MAX_BODY = 1024 * 1024


class ConfigServer(ThreadingHTTPServer):
    """A server that knows which installation its handlers are editing.

    It also remembers every session token it has handed out. A cookie is
    accepted only if it is one of those: cookies are not scoped by port, so a
    page on any other loopback port can set ``lxo_config`` to a value of its
    choosing and put the same value in a form. A token only this process
    could have made is one such a page cannot know.
    """

    installation: Installation

    # On Windows SO_REUSEADDR lets a second process bind a port another one is
    # listening on, and connections then go to whichever bound it first - an
    # older interface, or another program, would get the browser and the key.
    # Elsewhere it only allows a restart while old connections linger, which
    # is harmless and worth keeping.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sessions: set[str] = set()
        self._sessions_lock = threading.Lock()

    def issue_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._sessions_lock:
            self.sessions.add(token)
        return token

    def knows_session(self, token: str) -> bool:
        with self._sessions_lock:
            return token in self.sessions


class Handler(BaseHTTPRequestHandler):
    """Three pages, a handful of actions, and two guards in front of each."""

    server_version = f"lexware-office-mcp-config/{__version__}"

    # Set per request by _session_token().
    _session: str = ""
    _fresh_cookie: str | None = None

    @property
    def installation(self) -> Installation:
        return self.config_server.installation

    @property
    def config_server(self) -> ConfigServer:
        return self.server  # type: ignore[return-value]

    # --- plumbing ----------------------------------------------------------

    def log_message(self, *args: Any) -> None:
        """Silence. A request log of a single-user local page is noise."""

    def _session_token(self) -> str:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie is not our problem
            pass
        morsel = jar.get(_SESSION_COOKIE)
        if morsel and morsel.value and self.config_server.knows_session(morsel.value):
            self._fresh_cookie = None
            return str(morsel.value)
        # No cookie, or one this process never issued - planted by another
        # page, or left over from an earlier run. Either way a new one.
        self._fresh_cookie = self.config_server.issue_session()
        return self._fresh_cookie

    def _cookie_header(self) -> None:
        if self._fresh_cookie:
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}={self._fresh_cookie}; Path=/; "
                "SameSite=Strict; HttpOnly",
            )

    def _common_headers(self, body: bytes) -> None:
        self.send_header("Content-Length", str(len(body)))
        # The pages show the bearer token and name the files and the company.
        # None of that belongs in a browser cache.
        self.send_header("Cache-Control", "no-store")
        # No other page may frame these and trick a click out of someone, no
        # content type is guessed, and no address leaves in a Referer.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self._cookie_header()
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str = "text/html") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self._common_headers(body)
        self.wfile.write(body)

    def _download(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self._common_headers(body)
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send(404, page("Nicht gefunden", "<p>Diese Adresse gibt es nicht.</p>"))

    def _deny(self, reason: str) -> None:
        self._send(403, page("Abgelehnt", f'<p class="err">{esc(reason)}</p>'))

    def _host_ok(self) -> bool:
        """Whether the browser addressed this page by a loopback name.

        Checked on every request, reading ones included. A page elsewhere can
        point a name it controls at 127.0.0.1 - DNS rebinding - and then read
        these pages as its own origin, bearer token and all. Its ``Host`` is
        still its own name, so refusing anything but loopback closes that.

        **Not access control.** A browser writes the name it used, but any
        other client writes whatever it likes, so a machine that reaches a
        ``--host 0.0.0.0`` bind is answered as soon as it sends
        ``Host: localhost``. The port is not compared, so a container
        published under a different port still works.
        """
        target = _host_and_port(self.headers.get("Host", ""))
        return target is not None and target[0] in LOOPBACK_NAMES

    def _origin_ok(self) -> bool:
        """Whether a state-changing request came from this page.

        A request without ``Origin`` and without ``Referer`` is refused:
        every current browser sends one on a form post, so its absence means
        the request was not made by one.

        **The port counts.** Loopback alone would admit a page served by any
        other program on this machine. The source has to name the very host
        and port this request was sent to, which is what the ``Host`` header
        says - compared to that rather than to the bound port, so a container
        published under another port still works.
        """
        source = self.headers.get("Origin") or self.headers.get("Referer")
        if not source:
            return False
        parsed = urlparse(source)
        if parsed.scheme != "http":
            return False
        target = _host_and_port(self.headers.get("Host", ""))
        if target is None or target[0] not in LOOPBACK_NAMES:
            return False
        try:
            origin = ((parsed.hostname or "").lower(), parsed.port or 80)
        except ValueError:
            return False
        return origin == target

    def _csrf_ok(self, form: Form) -> bool:
        if self._fresh_cookie:
            return False  # no session cookie was presented at all
        sent = field(form, "_csrf")
        # As bytes: on two strings compare_digest raises TypeError for a
        # character outside ASCII, which a form field can carry.
        return bool(sent) and secrets.compare_digest(
            sent.encode(), self._session.encode()
        )

    # --- routing -----------------------------------------------------------

    def _wrong_host(self) -> None:
        logbook.configui.request_refused("host")
        self._send(
            403,
            page(
                "Abgelehnt",
                '<p class="err">Diese Seite ist nur als 127.0.0.1 oder '
                "localhost erreichbar.</p>",
            ),
        )

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names it
        if not self._host_ok():
            self._wrong_host()
            return
        self._session = self._session_token()
        try:
            self._route_get(urlparse(self.path).path)
        except ConfigError as exc:
            self._unreadable(exc)

    def _route_get(self, path: str) -> None:
        inst = self.installation
        if path in ("/", "/index.html"):
            self._send(200, pages.overview(inst, csrf=self._session))
        elif path == "/credentials":
            self._send(200, pages.credentials(inst, csrf=self._session))
        elif path == "/permissions":
            self._send(200, pages.permissions(inst, csrf=self._session))
        elif path == "/export":
            self._reply(actions.export(inst))
        else:
            self._not_found()

    def do_POST(self) -> None:  # noqa: N802 - the stdlib names it
        self._session = ""
        path = urlparse(self.path).path
        # Read the body first whatever happens, or the connection stalls -
        # but only up to a size no form here comes near. A larger claim is
        # refused unread and the connection closed, since reading it would
        # be exactly what the claim was for.
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            logbook.configui.request_refused("size")
            self.close_connection = True
            self._send(413, page("Zu groß", "<p>Diese Anfrage ist zu groß.</p>"))
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        if not self._host_ok():
            self._wrong_host()
            return
        self._session = self._session_token()

        routes: dict[str, actions.Action] = {
            "/check": actions.check,
            "/credentials": actions.save_key,
            "/bearer": actions.save_bearer,
            "/settings": actions.save_settings,
            "/permissions": actions.permissions,
        }
        action = routes.get(path)
        if action is None:
            self._not_found()
            return
        if not self._origin_ok():
            logbook.configui.request_refused("origin")
            self._deny(
                "Abgelehnt: die Anfrage kam nicht von dieser Seite "
                "(Origin oder Referer ist nicht lokal)."
            )
            return
        if not self._csrf_ok(form):
            logbook.configui.request_refused("token")
            self._deny(
                "Abgelehnt: das Sicherheitstoken fehlt oder passt nicht. "
                "Seite neu laden und noch einmal absenden."
            )
            return
        try:
            self._reply(action(self.installation, form, self._session))
        except ConfigError as exc:
            self._unreadable(exc)

    def _unreadable(self, exc: ConfigError) -> None:
        """A configuration file this page cannot read, said on the page.

        Every page reads the ``.env``. Left to the request thread, a file
        in the wrong encoding ended it with a traceback and the browser got
        an empty answer - on the very interface meant to repair the file.
        """
        self._send(
            500,
            page(
                "Datei nicht lesbar",
                f'<p class="err">{esc(str(exc))}</p>',
            ),
        )

    def _reply(self, reply: Reply | None) -> None:
        """Send what an action answered: a page, a download, or nothing there."""
        if reply is None:
            self._not_found()
        elif reply.download is not None:
            self._download(reply.body, reply.download)
        else:
            self._send(200, reply.body)


def _host_and_port(header: str) -> tuple[str, int] | None:
    """A ``Host`` header as a lower-case name and a port, or ``None``."""
    try:
        parsed = urlparse(f"//{header.strip()}")
        name, port = (parsed.hostname or "").lower(), parsed.port or 80
    except ValueError:
        return None
    return (name, port) if name else None


def serve(
    installation: Installation,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> None:
    """Run until interrupted. Everything it says goes to stderr.

    stdout stays free even here, where nothing would be listening to it: the
    command shares an entry point with a server for which stdout is the
    protocol, and one habit is easier to keep than two.
    """
    try:
        server = ConfigServer((host, port), Handler)
    except OSError as exc:
        print(
            f"Konnte {host}:{port} nicht öffnen: {exc.strerror or exc}. Läuft "
            "die Oberfläche schon? Sonst mit --port einen anderen Port wählen.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    server.installation = installation
    # The address a person opens, which is not always the one that was bound:
    # 0.0.0.0 is a bind, not a destination.
    reachable = DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host
    url = f"http://{reachable}:{port}/"
    print(f"Konfiguration im Browser: {url}", file=sys.stderr)
    if host not in LOOPBACK_NAMES:
        print(
            f"Achtung: gebunden an {host}, also nicht nur von diesem Rechner "
            "aus erreichbar. Die Seiten haben keine Anmeldung: wer diesen Port "
            "im Netz erreicht, kann sie aufrufen und den Schlüssel ändern. "
            "Außerhalb eines Containers nur mit --host 127.0.0.1 starten.",
            file=sys.stderr,
        )
    print(f".env:    {installation.env_path}", file=sys.stderr)
    print(f"Rechte:  {installation.policy_path}", file=sys.stderr)
    print(f"Profile: {installation.profiles.path}", file=sys.stderr)
    print("Beenden mit Strg+C.", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Beendet.", file=sys.stderr)
    finally:
        server.server_close()
