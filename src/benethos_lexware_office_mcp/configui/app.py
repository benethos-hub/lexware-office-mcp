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
"""

from __future__ import annotations

import dataclasses
import secrets
import sys
import threading
import webbrowser
from collections.abc import Callable
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__, logbook
from ..config import LOOPBACK_NAMES, ConfigError, load_settings
from ..envfile import update_env_file
from ..policy import known_tools
from . import pages, probe, transfer
from .profiles import ProfileError
from .render import esc, note, page
from .state import API_KEY, BEARER_KEY, EDITABLE_KEYS, Installation

__all__ = ["ConfigServer", "Handler", "serve"]

# A parsed form: every field a list, because `parse_qs` allows repeats and the
# checkbox per tool relies on that.
Form = dict[str, list[str]]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

_SESSION_COOKIE = "lxo_config"

# The largest form this interface accepts. An imported policy file is the
# biggest thing any of them carries, and that is a few kilobytes.
MAX_BODY = 1024 * 1024

# The name the file has on disk, so a download can simply replace one.
_EXPORT_NAME = "tools.json"


class ConfigServer(ThreadingHTTPServer):
    """A server that knows which installation its handlers are editing.

    It also remembers every session token it has handed out. A cookie is
    accepted only if it is one of those: cookies are not scoped by port, so a
    page on any other loopback port can set ``lxo_config`` to a value of its
    choosing and put the same value in a form. A token only this process
    could have made is one such a page cannot know.
    """

    installation: Installation

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
        It also keeps a ``--host 0.0.0.0`` bind from answering a machine on
        the network, which would reach it by an address of this one.
        The port is not compared, so a container published under a different
        port still works.
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
        sent = _field(form, "_csrf")
        return bool(sent) and secrets.compare_digest(sent, self._session)

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
        path = urlparse(self.path).path
        inst = self.installation
        if path in ("/", "/index.html"):
            self._send(200, pages.overview(inst, csrf=self._session))
        elif path == "/credentials":
            self._send(200, pages.credentials(inst, csrf=self._session))
        elif path == "/permissions":
            self._send(200, pages.permissions(inst, csrf=self._session))
        elif path == "/export":
            self._export()
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

        routes = {
            "/check": self._check,
            "/credentials": self._save_key,
            "/bearer": self._save_bearer,
            "/settings": self._save_settings,
            "/permissions": self._permissions,
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
        action(form)

    # --- actions -----------------------------------------------------------

    def _check(self, form: Form) -> None:
        account, message = probe.check(self.installation.settings)
        if account is None:
            body = pages.raw_message(esc(message), "bad")
        else:
            body = pages.raw_message(
                f"{esc(message)} {pages.account_summary(account)}", "good"
            )
        self._send(
            200, pages.overview(self.installation, csrf=self._session, message=body)
        )

    def _save_key(self, form: Form) -> None:
        inst = self.installation
        key = _field(form, "api_key")
        skip_check = bool(form.get("unchecked"))
        if not key:
            self._page_with(
                pages.credentials, "Kein Schlüssel eingegeben, nichts geändert."
            )
            return

        verified: probe.Account | None = None
        if not skip_check:
            probe_settings = dataclasses.replace(inst.settings, api_key=key)
            verified, message = probe.check(probe_settings)
            if verified is None:
                logbook.configui.key_refused()
                self._page_with(
                    pages.credentials,
                    f"Nicht gespeichert. {message}",
                    kind="bad",
                )
                return

        try:
            update_env_file(inst.env_path, {API_KEY: key})
        except (OSError, ValueError) as exc:
            self._page_with(
                pages.credentials, _write_failed(inst.env_path, exc), kind="bad"
            )
            return
        logbook.configui.key_saved(inst.env_path.name, verified is not None)
        inst.reload()
        suffix = (
            " Ungeprüft übernommen."
            if verified is None
            else f" Geprüft, das Konto lautet {verified.label}."
        )
        shadow = (
            " Achtung: eine Umgebungsvariable setzt ihn weiterhin außer Kraft."
            if inst.shadowed(API_KEY)
            else ""
        )
        self._page_with(
            pages.credentials,
            f"Schlüssel nach {inst.env_path} geschrieben.{suffix}{shadow}",
            kind="good",
        )

    def _save_bearer(self, form: Form) -> None:
        """Write the HTTP token, or make one. Never write an empty one.

        Empty means "leave alone" for the API key, where the field is blank
        by design. Here the field shows what is set, so blank can only mean
        the value was cleared - and a cleared token is a server that stops
        serving on its next start.
        """
        inst = self.installation
        if _field(form, "action") == "generate":
            token = secrets.token_urlsafe(32)
            done = "Neues Token erzeugt und gespeichert."
        else:
            token = _field(form, "bearer")
            if not token:
                self._page_with(
                    pages.credentials,
                    "Nicht gespeichert: ein leeres Token wäre kein Token. "
                    "Der Server startet den HTTP-Transport dann nicht.",
                    kind="bad",
                )
                return
            done = "Token gespeichert."

        try:
            update_env_file(inst.env_path, {BEARER_KEY: token})
        except (OSError, ValueError) as exc:
            self._page_with(
                pages.credentials, _write_failed(inst.env_path, exc), kind="bad"
            )
            return

        logbook.configui.token_saved(
            inst.env_path.name, _field(form, "action") == "generate"
        )
        inst.reload()
        shadow = (
            " Achtung: eine Umgebungsvariable setzt es weiterhin außer Kraft."
            if inst.shadowed(BEARER_KEY)
            else ""
        )
        self._page_with(
            pages.credentials,
            f"{done} Ein laufender Server übernimmt es beim nächsten Start, "
            f"jeder Client braucht es dann neu.{shadow}",
            kind="good",
        )

    def _save_settings(self, form: Form) -> None:
        inst = self.installation
        submitted = {key: _field(form, key) for key in EDITABLE_KEYS if key in form}
        # Validated by the same code the server uses, so a value accepted here
        # cannot be one that stops the server from starting later.
        proposed = {**inst.file_env(), **submitted}
        try:
            load_settings(env=proposed)
        except ConfigError as exc:
            # The server's own wording, quoted rather than translated. A German
            # paraphrase here would be a second copy of a rule that lives in
            # config.py, and the two would part company on the first change.
            self._page_with(
                pages.credentials,
                f"Nicht gespeichert, der Server würde das ablehnen: {exc}",
                kind="bad",
            )
            return
        try:
            update_env_file(inst.env_path, submitted)
        except (OSError, ValueError) as exc:
            self._page_with(
                pages.credentials, _write_failed(inst.env_path, exc), kind="bad"
            )
            return
        logbook.configui.settings_saved(inst.env_path.name, list(submitted))
        inst.reload()
        self._page_with(
            pages.credentials,
            f"{len(submitted)} Einstellungen nach {inst.env_path} geschrieben.",
            kind="good",
        )

    def _permissions(self, form: Form) -> None:
        """One form, seven buttons: the button's value says which."""
        chosen = [name for name in form.get("tool", []) if name in known_tools()]
        actions: dict[str, Callable[[], None]] = {
            "save": lambda: self._save_policy(chosen),
            "load": lambda: self._load_profile(form),
            "profile-save": lambda: self._save_profile(form, chosen),
            "profile-overwrite": lambda: self._overwrite_profile(form, chosen),
            "profile-delete": lambda: self._delete_profile(form),
            "policy-export": self._export,
            "policy-import": lambda: self._import_policy(form, chosen),
        }
        action = actions.get(_field(form, "action"))
        if action is None:
            self._not_found()
            return
        action()

    def _save_policy(self, chosen: list[str]) -> None:
        """Write the file. The one action here that changes what a server does."""
        inst = self.installation
        flags = {name: name in chosen for name in known_tools()}
        try:
            inst.policy.save(flags)
        except (OSError, ValueError) as exc:
            self._page_with(
                pages.permissions, _write_failed(inst.policy_path, exc), kind="bad"
            )
            return
        writers = sorted(n for n in chosen if known_tools()[n].access == "write")
        logbook.configui.policy_saved(
            inst.policy_path, len(chosen), len(flags), writers
        )
        text = f"{len(chosen)} von {len(flags)} Tools aktiv."
        if writers:
            text += (
                f" Davon dürfen {len(writers)} echte Buchhaltungsdaten ändern: "
                + ", ".join(writers)
                + "."
            )
        self._page_with(pages.permissions, text, kind="" if writers else "good")

    def _load_profile(self, form: Form) -> None:
        inst = self.installation
        name = _field(form, "profile")
        profile = inst.profiles.get(name)
        if profile is None:
            self._page_with(
                pages.permissions, f"Kein Profil namens {name}.", kind="bad"
            )
            return
        known = list(known_tools())
        newer = profile.newer_tools(known)
        unknown = profile.unknown(known)
        text = (
            f"Profil {profile.name} geladen, {len(profile.tools)} Tools. "
            "Noch nichts geschrieben — dafür unten auf „Rechte speichern“."
        )
        if newer:
            text += (
                f" {len(newer)} Tools sind neuer als das Profil und bleiben "
                "deshalb aus: " + ", ".join(newer) + "."
            )
        if unknown:
            text += f" Übergangen, weil es sie nicht mehr gibt: {', '.join(unknown)}."
        body = pages.permissions(
            inst,
            csrf=self._session,
            message=note(esc(text)),
            flags=profile.flags(known),
        )
        self._send(200, body)

    def _save_profile(self, form: Form, chosen: list[str]) -> None:
        """Create a profile under a new name, and only under a new one.

        A name that is already taken is refused rather than silently
        replacing what is there. Case and spacing do not distinguish two
        profiles: "nur lesend" beside "Nur lesend" is a duplicate a person
        cannot tell apart in the list, which sorts case-insensitively.
        Overwriting has a button of its own.
        """
        inst = self.installation
        name = _field(form, "profile_name")
        clash = inst.profiles.find(name)
        if clash is not None:
            self._page_with(
                pages.permissions,
                f"Es gibt schon ein Profil namens „{clash.name}“. Oben "
                "auswählen und überschreiben, oder einen anderen Namen nehmen.",
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        try:
            profile = inst.profiles.save(name, chosen, known_tools())
        except ProfileError as exc:
            self._page_with(
                pages.permissions,
                str(exc),
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        except OSError as exc:
            self._page_with(
                pages.permissions,
                _write_failed(inst.profiles.path, exc),
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        logbook.configui.profile_saved(profile.name, len(profile.tools), False)
        self._page_with(
            pages.permissions,
            f"Profil {profile.name} angelegt, {len(profile.tools)} Tools. "
            "Die Rechtedatei selbst ist unverändert.",
            kind="good",
            flags=_flags(chosen),
            opened="profiles",
        )

    def _overwrite_profile(self, form: Form, chosen: list[str]) -> None:
        """Replace the selected profile with what is ticked right now."""
        inst = self.installation
        name = _field(form, "profile")
        if inst.profiles.get(name) is None:
            self._page_with(
                pages.permissions,
                f"Kein Profil namens {name}.",
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        try:
            profile = inst.profiles.save(name, chosen, known_tools())
        except OSError as exc:
            self._page_with(
                pages.permissions,
                _write_failed(inst.profiles.path, exc),
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        logbook.configui.profile_saved(profile.name, len(profile.tools), True)
        self._page_with(
            pages.permissions,
            f"Profil {profile.name} überschrieben, {len(profile.tools)} Tools. "
            "Die Rechtedatei selbst ist unverändert.",
            kind="good",
            flags=_flags(chosen),
            opened="profiles",
        )

    def _delete_profile(self, form: Form) -> None:
        name = _field(form, "profile")
        gone = self.installation.profiles.delete(name)
        if gone:
            logbook.configui.profile_deleted(name)
        self._page_with(
            pages.permissions,
            f"Profil {name} gelöscht." if gone else f"Kein Profil namens {name}.",
            kind="good" if gone else "bad",
            opened="profiles",
        )

    # --- carrying the policy file ----------------------------------------

    def _export(self) -> None:
        """The policy file as a download, byte for byte what is on disk."""
        self._download(
            transfer.dumps(self.installation.policy.as_map()).encode("utf-8"),
            _EXPORT_NAME,
        )

    def _import_policy(self, form: Form, chosen: list[str]) -> None:
        """Read a policy file into the form. Saving is still a separate act.

        The rule is the one `--tools sync` follows: a tool the file does not
        name stays **off**, because that is what an unmentioned tool means
        everywhere else in this project. A file written before a tool existed
        therefore leaves it switched off rather than guessing, and how many
        those are is said out loud instead of being left to be noticed.
        """
        text = _field(form, "bundle")
        try:
            arriving = transfer.parse(text)
        except transfer.TransferError as exc:
            self._page_with(
                pages.permissions,
                str(exc),
                kind="bad",
                flags=_flags(chosen),
                opened="policy",
            )
            return

        known = known_tools()
        flags = {name: arriving.get(name, False) for name in known}
        newer = sorted(name for name in known if name not in arriving)
        unknown = sorted(name for name in arriving if name not in known)

        on = sum(flags.values())
        text_out = (
            f"Rechtedatei eingelesen, {on} von {len(known)} Tools angehakt. "
            "Geschrieben ist noch nichts — dafür unten auf „Rechte speichern“."
        )
        if newer:
            text_out += (
                f" {len(newer)} Tools nennt die Datei nicht und bleiben "
                "deshalb aus: " + ", ".join(newer) + "."
            )
        if unknown:
            text_out += (
                f" Übergangen, weil es sie hier nicht gibt: {', '.join(unknown)}."
            )
        self._send(
            200,
            pages.permissions(
                self.installation,
                csrf=self._session,
                message=note(esc(text_out)),
                flags=flags,
                opened="policy",
            ),
        )

    # --- one small convenience ---------------------------------------------

    def _page_with(
        self,
        render: Callable[..., bytes],
        text: str,
        *,
        kind: str = "",
        flags: dict[str, bool] | None = None,
        opened: str = "",
    ) -> None:
        extra: dict[str, Any] = {}
        if flags is not None:
            extra["flags"] = flags
        if opened:
            extra["opened"] = opened
        self._send(
            200,
            render(
                self.installation,
                csrf=self._session,
                message=pages.message_box(text, kind),
                **extra,
            ),
        )


def _field(form: Form, name: str) -> str:
    """One single-valued field of a form, stripped, empty when absent."""
    return form.get(name, [""])[0].strip()


def _write_failed(path: Path, exc: OSError | ValueError) -> str:
    """Why a file was not written. A refused value is quoted, not translated.

    One sentence for the three files this interface writes. The path is
    shown: this page is read by the person sitting at the machine, who is
    the one who can do something about a directory they do not own.

    Called exactly where a write failed, so it is also where stderr hears
    of it.
    """
    logbook.configui.write_failed(path, exc)
    if isinstance(exc, ValueError):
        return f"Nicht gespeichert: {exc}"
    return f"Konnte {path} nicht schreiben: {exc.strerror or exc}"


def _host_and_port(header: str) -> tuple[str, int] | None:
    """A ``Host`` header as a lower-case name and a port, or ``None``."""
    try:
        parsed = urlparse(f"//{header.strip()}")
        name, port = (parsed.hostname or "").lower(), parsed.port or 80
    except ValueError:
        return None
    return (name, port) if name else None


def _flags(chosen: list[str]) -> dict[str, bool]:
    return {name: name in chosen for name in known_tools()}


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
    server = ConfigServer((host, port), Handler)
    server.installation = installation
    # The address a person opens, which is not always the one that was bound:
    # 0.0.0.0 is a bind, not a destination.
    reachable = DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host
    url = f"http://{reachable}:{port}/"
    print(f"Konfiguration im Browser: {url}", file=sys.stderr)
    if host not in LOOPBACK_NAMES:
        print(
            f"Achtung: gebunden an {host}, also nicht nur von diesem Rechner "
            "aus erreichbar. Die Seiten haben keine Anmeldung und antworten "
            "nur, wenn sie als 127.0.0.1 oder localhost aufgerufen werden.",
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
