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
the ``Origin`` or ``Referer`` has to be loopback, and a random token from a
``SameSite=Strict`` cookie has to come back in the form.
"""

from __future__ import annotations

import dataclasses
import secrets
import sys
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..config import ConfigError, load_settings
from ..envfile import update_env_file
from ..policy import known_tools
from . import pages, probe, transfer
from .profiles import ProfileError
from .render import esc, note, page
from .state import API_KEY, BEARER_KEY, EDITABLE_KEYS, Installation

__all__ = ["ConfigServer", "Handler", "serve"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

_SESSION_COOKIE = "lxo_config"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# The name the file has on disk, so a download can simply replace one.
_EXPORT_NAME = "tools.json"


class ConfigServer(ThreadingHTTPServer):
    """A server that knows which installation its handlers are editing."""

    installation: Installation


class Handler(BaseHTTPRequestHandler):
    """Three pages, a handful of actions, and two guards in front of each."""

    server_version = f"lexware-office-mcp-config/{__version__}"

    # Set per request by _session_token().
    _session: str = ""
    _fresh_cookie: str | None = None

    @property
    def installation(self) -> Installation:
        return self.server.installation  # type: ignore[attr-defined]

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
        if morsel and morsel.value:
            self._fresh_cookie = None
            return str(morsel.value)
        self._fresh_cookie = secrets.token_urlsafe(32)
        return self._fresh_cookie

    def _cookie_header(self) -> None:
        if self._fresh_cookie:
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}={self._fresh_cookie}; Path=/; "
                "SameSite=Strict; HttpOnly",
            )

    def _send(self, status: int, body: bytes, content_type: str = "text/html") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cookie_header()
        self.end_headers()
        self.wfile.write(body)

    def _download(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self._cookie_header()
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send(404, page("Nicht gefunden", "<p>Diese Adresse gibt es nicht.</p>"))

    def _deny(self, reason: str) -> None:
        self._send(403, page("Abgelehnt", f'<p class="err">{esc(reason)}</p>'))

    def _origin_ok(self) -> bool:
        """Whether a state-changing request came from this page.

        A request without ``Origin`` and without ``Referer`` is refused:
        every current browser sends one on a form post, so its absence means
        the request was not made by one.
        """
        source = self.headers.get("Origin") or self.headers.get("Referer")
        if not source:
            return False
        parsed = urlparse(source)
        if parsed.scheme not in ("http", "https"):
            return False
        return (parsed.hostname or "").lower() in _LOOPBACK

    def _csrf_ok(self, form: dict[str, list[str]]) -> bool:
        if self._fresh_cookie:
            return False  # no session cookie was presented at all
        sent = (form.get("_csrf", [""])[0]).strip()
        return bool(sent) and secrets.compare_digest(sent, self._session)

    # --- routing -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names it
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
        self._session = self._session_token()
        path = urlparse(self.path).path
        # Read the body first whatever happens, or the connection stalls.
        length = int(self.headers.get("Content-Length", 0) or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))

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
            self._deny(
                "Abgelehnt: die Anfrage kam nicht von dieser Seite "
                "(Origin oder Referer ist nicht lokal)."
            )
            return
        if not self._csrf_ok(form):
            self._deny(
                "Abgelehnt: das Sicherheitstoken fehlt oder passt nicht. "
                "Seite neu laden und noch einmal absenden."
            )
            return
        action(form)

    # --- actions -----------------------------------------------------------

    def _check(self, form: dict[str, list[str]]) -> None:
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

    def _save_key(self, form: dict[str, list[str]]) -> None:
        inst = self.installation
        key = (form.get("api_key", [""])[0]).strip()
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
                self._page_with(
                    pages.credentials,
                    f"Nicht gespeichert. {message}",
                    kind="bad",
                )
                return

        try:
            update_env_file(inst.env_path, {API_KEY: key})
        except OSError as exc:
            self._page_with(
                pages.credentials,
                f"Konnte {inst.env_path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
            )
            return
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

    def _save_bearer(self, form: dict[str, list[str]]) -> None:
        """Write the HTTP token, or make one. Never write an empty one.

        Empty means "leave alone" for the API key, where the field is blank
        by design. Here the field shows what is set, so blank can only mean
        the value was cleared - and a cleared token is a server that stops
        serving on its next start.
        """
        inst = self.installation
        if form.get("action", [""])[0] == "generate":
            token = secrets.token_urlsafe(32)
            done = "Neues Token erzeugt und gespeichert."
        else:
            token = (form.get("bearer", [""])[0]).strip()
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
        except OSError as exc:
            self._page_with(
                pages.credentials,
                f"Konnte {inst.env_path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
            )
            return

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

    def _save_settings(self, form: dict[str, list[str]]) -> None:
        inst = self.installation
        submitted = {
            key: (form.get(key, [""])[0]).strip()
            for key in EDITABLE_KEYS
            if key in form
        }
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
        except OSError as exc:
            self._page_with(
                pages.credentials,
                f"Konnte {inst.env_path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
            )
            return
        inst.reload()
        self._page_with(
            pages.credentials,
            f"{len(submitted)} Einstellungen nach {inst.env_path} geschrieben.",
            kind="good",
        )

    def _permissions(self, form: dict[str, list[str]]) -> None:
        inst = self.installation
        action = (form.get("action", [""])[0]).strip()
        chosen = [name for name in form.get("tool", []) if name in known_tools()]

        if action == "load":
            self._load_profile(form)
            return
        if action == "profile-save":
            self._save_profile(form, chosen)
            return
        if action == "profile-overwrite":
            self._overwrite_profile(form, chosen)
            return
        if action == "profile-delete":
            self._delete_profile(form)
            return
        if action == "policy-export":
            self._export()
            return
        if action == "policy-import":
            self._import_policy(form, chosen)
            return
        if action != "save":
            self._not_found()
            return

        flags = {name: name in chosen for name in known_tools()}
        try:
            inst.policy.save(flags)
        except (OSError, ValueError) as exc:
            self._page_with(
                pages.permissions,
                f"Konnte {inst.policy_path} nicht schreiben: {exc}",
                kind="bad",
            )
            return
        writers = sorted(n for n in chosen if known_tools()[n].access == "write")
        text = f"{len(chosen)} von {len(flags)} Tools aktiv."
        if writers:
            text += (
                f" Davon dürfen {len(writers)} echte Buchhaltungsdaten ändern: "
                + ", ".join(writers)
                + "."
            )
        self._page_with(pages.permissions, text, kind="" if writers else "good")

    def _load_profile(self, form: dict[str, list[str]]) -> None:
        inst = self.installation
        name = (form.get("profile", [""])[0]).strip()
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

    def _save_profile(self, form: dict[str, list[str]], chosen: list[str]) -> None:
        """Create a profile under a new name, and only under a new one.

        A name that is already taken is refused rather than silently
        replacing what is there. Case and spacing do not distinguish two
        profiles: "nur lesend" beside "Nur lesend" is a duplicate a person
        cannot tell apart in the list, which sorts case-insensitively.
        Overwriting has a button of its own.
        """
        inst = self.installation
        name = (form.get("profile_name", [""])[0]).strip()
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
                f"Konnte {inst.profiles.path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        self._page_with(
            pages.permissions,
            f"Profil {profile.name} angelegt, {len(profile.tools)} Tools. "
            "Die Rechtedatei selbst ist unverändert.",
            kind="good",
            flags=_flags(chosen),
            opened="profiles",
        )

    def _overwrite_profile(self, form: dict[str, list[str]], chosen: list[str]) -> None:
        """Replace the selected profile with what is ticked right now."""
        inst = self.installation
        name = (form.get("profile", [""])[0]).strip()
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
                f"Konnte {inst.profiles.path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
                flags=_flags(chosen),
                opened="profiles",
            )
            return
        self._page_with(
            pages.permissions,
            f"Profil {profile.name} überschrieben, {len(profile.tools)} Tools. "
            "Die Rechtedatei selbst ist unverändert.",
            kind="good",
            flags=_flags(chosen),
            opened="profiles",
        )

    def _delete_profile(self, form: dict[str, list[str]]) -> None:
        name = (form.get("profile", [""])[0]).strip()
        gone = self.installation.profiles.delete(name)
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

    def _import_policy(self, form: dict[str, list[str]], chosen: list[str]) -> None:
        """Read a policy file into the form. Saving is still a separate act.

        The rule is the one `--tools sync` follows: a tool the file does not
        name stays **off**, because that is what an unmentioned tool means
        everywhere else in this project. A file written before a tool existed
        therefore leaves it switched off rather than guessing, and how many
        those are is said out loud instead of being left to be noticed.
        """
        text = form.get("bundle", [""])[0]
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
        render: Any,
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
    if host not in _LOOPBACK:
        print(
            f"Achtung: gebunden an {host}, also nicht nur von diesem Rechner "
            "aus erreichbar. Die Seiten haben keine Anmeldung.",
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
