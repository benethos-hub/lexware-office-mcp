"""The local web server that puts the three pages in a browser.

**Never part of the MCP server.** That one speaks JSON-RPC over stdio and must
keep stdout to itself. This is a separate command, started by a person, that
serves on the loopback interface and stops when they are done. The two share
their configuration modules and nothing else.

**It binds 127.0.0.1 and offers no way to change that.** The pages have no
login, because a page that only the local machine can reach does not need one
— and the moment it could be reached from elsewhere it would need one badly.
Refusing the choice is the simplest way to keep that true.

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
from .state import API_KEY, EDITABLE_KEYS, Installation

__all__ = ["ConfigServer", "Handler", "serve"]

HOST = "127.0.0.1"
DEFAULT_PORT = 8770

_SESSION_COOKIE = "lxo_config"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

_EXPORT_NAME = "lexware-office-mcp-profile.json"


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

    def _save_settings(self, form: dict[str, list[str]]) -> None:
        inst = self.installation
        submitted = {
            key: (form.get(key, [""])[0]).strip()
            for key in EDITABLE_KEYS
            if key in form
        }
        # Validated by the same code the server uses, so a value accepted here
        # cannot be one that stops the server from starting later.
        proposed = {**inst.searched_env(), **submitted}
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
        if action == "profile-delete":
            self._delete_profile(form)
            return
        if action == "profile-export":
            self._export()
            return
        if action == "profile-import":
            self._import_profiles(form, chosen)
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
                f"Konnte {inst.settings.policy_file()} nicht schreiben: {exc}",
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
        inst = self.installation
        name = (form.get("profile_name", [""])[0]).strip()
        existed = name in inst.profiles.all()
        try:
            profile = inst.profiles.save(name, chosen, known_tools())
        except ProfileError as exc:
            self._page_with(
                pages.permissions, str(exc), kind="bad", flags=_flags(chosen)
            )
            return
        except OSError as exc:
            self._page_with(
                pages.permissions,
                f"Konnte {inst.profiles.path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
                flags=_flags(chosen),
            )
            return
        verb = "überschrieben" if existed else "gespeichert"
        self._page_with(
            pages.permissions,
            f"Profil {profile.name} {verb}, {len(profile.tools)} Tools. "
            "Die Rechtedatei selbst ist unverändert.",
            kind="good",
            flags=_flags(chosen),
        )

    def _delete_profile(self, form: dict[str, list[str]]) -> None:
        name = (form.get("profile", [""])[0]).strip()
        gone = self.installation.profiles.delete(name)
        self._page_with(
            pages.permissions,
            f"Profil {name} gelöscht." if gone else f"Kein Profil namens {name}.",
            kind="good" if gone else "bad",
        )

    # --- carrying the profiles ------------------------------------------

    def _export(self) -> None:
        """The saved profiles as a download. Nothing else travels."""
        document = transfer.build(self.installation.profiles.all(), version=__version__)
        self._download(transfer.dumps(document).encode("utf-8"), _EXPORT_NAME)

    def _import_profiles(self, form: dict[str, list[str]], chosen: list[str]) -> None:
        """Add profiles from a file. No permission changes, so no preview.

        A profile is a list of names to choose from later. Nothing here
        reaches `tools.json`, which is what makes this safe to apply straight
        away - unlike the configuration bundle this replaced, which could
        have switched tools on for an account it was never written for.
        """
        inst = self.installation
        text = form.get("bundle", [""])[0]
        try:
            arriving = transfer.parse(text)
        except transfer.TransferError as exc:
            self._page_with(
                pages.permissions, str(exc), kind="bad", flags=_flags(chosen)
            )
            return
        try:
            overwritten = inst.profiles.merge(arriving)
        except OSError as exc:
            self._page_with(
                pages.permissions,
                f"Konnte {inst.profiles.path} nicht schreiben: {exc.strerror or exc}",
                kind="bad",
                flags=_flags(chosen),
            )
            return
        added = sorted(name for name in arriving if name not in overwritten)
        parts = [f"{len(arriving)} Profile eingelesen"]
        if added:
            parts.append("neu: " + ", ".join(added))
        if overwritten:
            parts.append("überschrieben: " + ", ".join(overwritten))
        self._page_with(
            pages.permissions,
            ". ".join(parts) + ". An den Rechten ändert das nichts.",
            kind="good",
            flags=_flags(chosen),
        )

    # --- one small convenience ---------------------------------------------

    def _page_with(
        self,
        render: Any,
        text: str,
        *,
        kind: str = "",
        flags: dict[str, bool] | None = None,
    ) -> None:
        extra = {"flags": flags} if flags is not None else {}
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
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> None:
    """Run until interrupted. Everything it says goes to stderr.

    stdout stays free even here, where nothing would be listening to it: the
    command shares an entry point with a server for which stdout is the
    protocol, and one habit is easier to keep than two.
    """
    server = ConfigServer((HOST, port), Handler)
    server.installation = installation
    url = f"http://{HOST}:{port}/"
    print(f"Konfiguration im Browser: {url}", file=sys.stderr)
    print(f".env:    {installation.env_path}", file=sys.stderr)
    print(f"Rechte:  {installation.settings.policy_file()}", file=sys.stderr)
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
