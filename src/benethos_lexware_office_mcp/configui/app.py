"""The local web server that puts the four pages in a browser.

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

**And every page asks for the start code** the process made when it started
and wrote to stderr, with the address, before it shows anything but the
field to type it into. The ``Host`` and ``Origin`` checks keep other sites
out, the code keeps out the other processes and users of the same machine,
which can reach a loopback port as well as the browser can. Once a session
has given it, the cookie carries the sign-in.

What a request that passes both then does is :mod:`.actions`. This module is
the HTTP around it: sessions, headers, the guards and the routing.
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__, logbook
from ..errors import ConfigError
from ..settings import LOOPBACK_NAMES
from . import DEFAULT_HOST, DEFAULT_PORT, actions, pages, templates
from .actions import Form, Reply, field
from .pages import Message, Page
from .state import Installation

__all__ = ["ConfigServer", "Handler", "serve"]

_SESSION_COOKIE = "lxo_config"

# Files from this origin only: no inline style, no inline script, no inline
# handler, nothing from elsewhere. The three directives `default-src` does
# not cover are named, so no other page can frame these, and a form can
# post nowhere but here.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

# Wrong start codes answered at once. Each one after these waits first, one
# at a time, so the waits cannot be run around in parallel either.
FREE_TRIES = 5
WAIT_SECONDS = 2.0

# How long the process stays after "Beenden" was answered: long enough for
# the browser to fetch the stylesheet of the page that says so.
LINGER_SECONDS = 1.0

# The largest form this interface accepts. An imported policy file is the
# biggest thing any of them carries, and that is a few kilobytes.
MAX_BODY = 1024 * 1024

# The pages a GET can open, by address. What a form left for one of them,
# the ticks of a loaded profile for instance, is passed as keywords.
PAGES: dict[str, Callable[..., Page]] = {
    "/": pages.overview,
    "/index.html": pages.overview,
    "/credentials": pages.credentials,
    "/permissions": pages.permissions,
    "/settings": pages.settings,
}


@dataclass(frozen=True)
class Once:
    """What a form that went through leaves for the page after the redirect.

    The message is shown on whichever page opens next. ``view`` only on the
    page at ``address``, the one the form redirected to.
    """

    address: str
    message: Message | None
    view: dict[str, Any]


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
        self._once: dict[str, Once] = {}
        # The start code, made once, written to stderr, and asked for by
        # every page until a session has given it.
        self.code = secrets.token_urlsafe(16)
        self._signed_in: set[str] = set()
        self._wrong = 0
        self._trying = threading.Lock()
        # How a wrong code waits. A test replaces it, so it waits for nothing.
        self.pause: Callable[[float], None] = time.sleep
        # Set when "Beenden" on a page ended the process, and how long the
        # process lingers after answering it.
        self.stopped_from_page = False
        self.linger = LINGER_SECONDS
        # One action at a time. Each reads a file, changes it and writes it
        # back - the .env, the policy, the profiles - and every request has
        # a thread of its own, so two tabs saving at once each wrote what
        # they had read, and the first save was lost.
        self.acting = threading.Lock()

    def issue_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._sessions_lock:
            self.sessions.add(token)
        return token

    def knows_session(self, token: str) -> bool:
        with self._sessions_lock:
            return token in self.sessions

    def stop_after_actions(self) -> None:
        """Stop serving once no action is writing a file.

        The request threads are daemons and would not outlive the process,
        so a save cut off halfway is what waiting here prevents. A form that
        arrives meanwhile is refused, see the handler.
        """
        with self.acting:
            self.shutdown()

    def signed_in(self, session: str) -> bool:
        """Whether this session has given the start code."""
        with self._sessions_lock:
            return session in self._signed_in

    def try_code(self, session: str, typed: str) -> bool:
        """Sign ``session`` in if ``typed`` is the start code.

        After :data:`FREE_TRIES` wrong codes every attempt waits first, and
        attempts are taken one at a time. A right code starts the count over.
        """
        with self._trying:
            if self._wrong >= FREE_TRIES:
                self.pause(WAIT_SECONDS)
            # As bytes, for the reason _csrf_ok gives.
            if typed and secrets.compare_digest(typed.encode(), self.code.encode()):
                self._wrong = 0
                with self._sessions_lock:
                    self._signed_in.add(session)
                return True
            self._wrong += 1
            return False

    def leave(self, session: str, once: Once) -> None:
        """Keep ``once`` for the next page this session opens.

        Held here beside the session rather than in the URL, so a link
        cannot put words into the interface.
        """
        with self._sessions_lock:
            self._once[session] = once

    def take(self, session: str) -> Once | None:
        """What the last form left for this session, once."""
        with self._sessions_lock:
            return self._once.pop(session, None)


class Handler(BaseHTTPRequestHandler):
    """Four pages, a handful of actions, and two guards in front of each."""

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
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self._cookie_header()
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str = "text/html") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self._common_headers(body)
        self.wfile.write(body)

    def _page(self, status: int, page: Page, message: Message | None = None) -> None:
        """A page in its frame, carrying this session's token."""
        self._send(status, page.html(csrf=self._session, message=message))

    def _redirect(self, address: str) -> None:
        """See Other: the browser asks for ``address`` with a GET."""
        self.send_response(303)
        self.send_header("Location", address)
        self._common_headers(b"")

    def _download(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self._common_headers(body)
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._page(404, pages.error("Nicht gefunden", "Diese Adresse gibt es nicht."))

    def _deny(self, reason: str) -> None:
        self._page(403, pages.error("Abgelehnt", reason))

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
        self._deny("Diese Seite ist nur als 127.0.0.1 oder localhost erreichbar.")

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names it
        if not self._host_ok():
            self._wrong_host()
            return
        self._session = self._session_token()
        address = urlparse(self.path)
        if address.path.startswith("/static/"):
            # The stylesheet and the script, which the code page needs too.
            self._static(address.path.removeprefix("/static/"))
            return
        typed = parse_qs(address.query).get("code")
        if typed is not None:
            self._sign_in(typed[0], then=address.path)
            return
        if not self.config_server.signed_in(self._session):
            self._page(403, pages.code())
            return
        try:
            self._route_get(address.path)
        except ConfigError as exc:
            self._unreadable(exc)

    def _sign_in(self, typed: str, *, then: str) -> None:
        """The start code, from the address or from the field.

        Right, and the session is signed in and sent on to ``then`` - which
        for the address the start printed takes the code out of the URL.
        Wrong, and the field comes back with the reason.
        """
        if self.config_server.try_code(self._session, typed.strip()):
            logbook.configui.signed_in()
            self._redirect(then)
            return
        logbook.configui.request_refused("code")
        self._page(
            403,
            pages.code(),
            Message(
                "Dieser Code passt nicht. Er steht in der Zeile, die setup "
                "beim Start ausgegeben hat.",
                "err",
            ),
        )

    def _route_get(self, path: str) -> None:
        inst = self.installation
        page = PAGES.get(path)
        if page is not None:
            once = (
                None if self._fresh_cookie else self.config_server.take(self._session)
            )
            view = once.view if once is not None and once.address == path else {}
            self._page(200, page(inst, **view), once.message if once else None)
        elif path == "/export":
            self._reply(actions.export(inst))
        else:
            self._not_found()

    def _static(self, name: str) -> None:
        """The stylesheet or the script, and nothing else under that path."""
        found = templates.static(name)
        if found is None:
            self._not_found()
            return
        body, content_type = found
        self._send(200, body, content_type)

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
            self._page(413, pages.error("Zu groß", "Diese Anfrage ist zu groß."))
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        # Blank fields kept: an emptied setting is how a person asks for the
        # default back, and dropped here it never reached the action, which
        # left the old value in place and reported success.
        form = parse_qs(raw, keep_blank_values=True)
        if not self._host_ok():
            self._wrong_host()
            return
        self._session = self._session_token()

        routes: dict[str, actions.Action | None] = {
            # Answered here rather than by an action: the first decides the
            # sign-in, the second ends the process the actions run in.
            "/code": None,
            "/shutdown": None,
            "/check": actions.check,
            "/credentials": actions.save_key,
            "/bearer": actions.save_bearer,
            "/settings": actions.save_settings,
            "/permissions": actions.permissions,
        }
        if path not in routes:
            self._not_found()
            return
        action = routes[path]
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
        if path == "/code":
            self._sign_in(field(form, "code"), then="/")
            return
        if not self.config_server.signed_in(self._session):
            logbook.configui.request_refused("code")
            self._page(403, pages.code())
            return
        if self.config_server.stopped_from_page:
            # Ending: nothing more is written, "Beenden" included again.
            self._page(503, pages.stopped())
            return
        if action is None:
            self._stop()
            return
        try:
            with self.config_server.acting:
                reply = action(self.installation, form)
            self._reply(reply)
        except ConfigError as exc:
            self._unreadable(exc)

    def _stop(self) -> None:
        """End the process from the page, as Ctrl+C ends it from the terminal.

        The answer goes out first, and the server stops a moment later from
        a thread of its own: ``shutdown`` waits for the serving loop, which
        would wait for this request. Behind every guard a form has, the
        start code included, so the worst a stranger could do is nothing.
        """
        server = self.config_server
        server.stopped_from_page = True
        self._page(200, pages.stopped())
        timer = threading.Timer(server.linger, server.stop_after_actions)
        timer.daemon = True
        timer.start()

    def _unreadable(self, exc: ConfigError) -> None:
        """A configuration file this page cannot read, said on the page.

        Every page reads the ``.env``. Left to the request thread, a file
        in the wrong encoding ended it with a traceback and the browser got
        an empty answer - on the very interface meant to repair the file.
        """
        self._page(500, pages.error("Datei nicht lesbar", str(exc)))

    def _reply(self, reply: Reply | None) -> None:
        """Send what an action answered: on to the next page, a refusal, a
        download, or nothing there."""
        if reply is None:
            self._not_found()
        elif reply.redirect is not None:
            self.config_server.leave(
                self._session, Once(reply.redirect, reply.message, reply.view)
            )
            self._redirect(reply.redirect)
        elif reply.download is not None:
            self._download(reply.body, reply.download)
        elif reply.page is not None:
            self._page(reply.status, reply.page, reply.message)


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
    """Run until interrupted or ended from a page.

    Everything it says is a line of the log on stderr, English like every
    other: the German of this interface is for its pages. stdout stays free
    even here, where nothing would be listening to it: the command shares an
    entry point with a server for which stdout is the protocol, and one habit
    is easier to keep than two.
    """
    try:
        server = ConfigServer((host, port), Handler)
    except OSError as exc:
        logbook.configui.port_taken(host, port, exc)
        raise SystemExit(1) from None
    server.installation = installation
    # The address a person opens, which is not always the one that was bound:
    # 0.0.0.0 is a bind, not a destination.
    reachable = DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host
    # The code goes with the address, so the browser this opens is signed
    # in at once and the line is all a person copies from a container's log.
    logbook.configui.serving(reachable, port, server.code)
    if host not in LOOPBACK_NAMES:
        logbook.configui.bound_beyond_loopback(host)
    logbook.configui.editing("settings", installation.env_path)
    logbook.configui.editing("policy", installation.policy_path)
    logbook.configui.editing("profiles", installation.profiles.path)
    if open_browser:
        webbrowser.open(f"http://{reachable}:{port}/?code={server.code}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logbook.configui.interrupted()
    else:
        if server.stopped_from_page:
            logbook.configui.stopped_from_page()
    finally:
        server.server_close()
