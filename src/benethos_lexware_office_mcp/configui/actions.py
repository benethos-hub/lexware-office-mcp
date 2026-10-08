"""What each form on the three pages does, as plain functions.

An action takes the installation it edits, the submitted form and the
session's CSRF token, which every page it renders carries, and answers with a
:class:`Reply`: a page with a message on it, or a file to download. ``None``
means there is no such action, which the handler answers as a 404.

Nothing here knows about HTTP. By the time an action runs, the handler in
:mod:`.app` has checked the ``Host``, the ``Origin`` and the token, and
whatever an action answers it sends as it is. That split is what lets an
action be read, and changed, without the guards in the way.
"""

from __future__ import annotations

import dataclasses
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import logbook
from ..errors import ConfigError
from ..policy import known_tools
from ..settings import LOG_LEVELS, load_settings
from ..settings.envfile import update_env_file
from ..settings.parse import credential
from . import pages, probe, transfer
from .profiles import ProfileError
from .render import esc, note
from .state import API_KEY, BEARER_KEY, EDITABLE_KEYS, Installation

__all__ = [
    "Action",
    "Form",
    "Reply",
    "check",
    "export",
    "field",
    "permissions",
    "save_bearer",
    "save_key",
    "save_settings",
]

# A parsed form: every field a list, because `parse_qs` allows repeats and the
# checkbox per tool relies on that.
Form = dict[str, list[str]]

# The name the file has on disk, so a download can simply replace one.
_EXPORT_NAME = "tools.json"

LOG_LEVEL_KEY = "LXO_MCP_LOG_LEVEL"


@dataclasses.dataclass(frozen=True)
class Reply:
    """What an action answers with: a page, or a file under ``download``."""

    body: bytes
    download: str | None = None


Action = Callable[[Installation, Form, str], Reply | None]


def check(inst: Installation, form: Form, csrf: str) -> Reply:
    account, message = probe.check(inst.settings)
    if account is None:
        body = pages.raw_message(esc(message), "bad")
    else:
        body = pages.raw_message(
            f"{esc(message)} {pages.account_summary(account)}", "good"
        )
    return Reply(pages.overview(inst, csrf=csrf, message=body))


def save_key(inst: Installation, form: Form, csrf: str) -> Reply:
    key = field(form, "api_key")
    skip_check = bool(form.get("unchecked"))
    if not key:
        return _page_with(
            inst, csrf, pages.credentials, "Kein Schlüssel eingegeben, nichts geändert."
        )

    try:
        credential(key, name=API_KEY)
    except ConfigError as exc:
        # The server's own wording, quoted as for any refused setting.
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            f"Nicht gespeichert, der Server würde das ablehnen: {exc}",
            kind="bad",
        )

    verified: probe.Account | None = None
    if not skip_check:
        probe_settings = dataclasses.replace(inst.settings, api_key=key)
        verified, message = probe.check(probe_settings, keep=False)
        if verified is None:
            logbook.configui.key_refused()
            return _page_with(
                inst,
                csrf,
                pages.credentials,
                f"Nicht gespeichert. {message}",
                kind="bad",
            )

    try:
        update_env_file(inst.env_path, {API_KEY: key})
    except (OSError, ValueError) as exc:
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            _write_failed(inst.env_path, exc),
            kind="bad",
        )
    if verified is not None:
        probe.remember(verified)
    logbook.configui.key_saved(inst.env_path.name, verified is not None)
    refused = _reloaded(inst)
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
    return _page_with(
        inst,
        csrf,
        pages.credentials,
        f"Schlüssel nach {inst.env_path} geschrieben.{suffix}{shadow}{refused}",
        kind="bad" if refused else "good",
    )


def save_bearer(inst: Installation, form: Form, csrf: str) -> Reply:
    """Write the HTTP token, or make one. Never write an empty one.

    Empty means "leave alone" for the API key, where the field is blank by
    design. Here the field shows what is set, so blank can only mean the
    value was cleared - and a cleared token is a server that stops serving on
    its next start.
    """
    if field(form, "action") == "generate":
        token = secrets.token_urlsafe(32)
        done = "Neues Token erzeugt und gespeichert."
    else:
        token = field(form, "bearer")
        if not token:
            return _page_with(
                inst,
                csrf,
                pages.credentials,
                "Nicht gespeichert: ein leeres Token wäre kein Token. "
                "Der Server startet den HTTP-Transport dann nicht.",
                kind="bad",
            )
        try:
            credential(token, name=BEARER_KEY)
        except ConfigError as exc:
            return _page_with(
                inst,
                csrf,
                pages.credentials,
                f"Nicht gespeichert, der Server würde das ablehnen: {exc}",
                kind="bad",
            )
        done = "Token gespeichert."

    try:
        update_env_file(inst.env_path, {BEARER_KEY: token})
    except (OSError, ValueError) as exc:
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            _write_failed(inst.env_path, exc),
            kind="bad",
        )

    logbook.configui.token_saved(
        inst.env_path.name, field(form, "action") == "generate"
    )
    refused = _reloaded(inst)
    shadow = (
        " Achtung: eine Umgebungsvariable setzt es weiterhin außer Kraft."
        if inst.shadowed(BEARER_KEY)
        else ""
    )
    return _page_with(
        inst,
        csrf,
        pages.credentials,
        f"{done} Ein laufender Server übernimmt es beim nächsten Start, "
        f"jeder Client braucht es dann neu.{shadow}{refused}",
        kind="bad" if refused else "good",
    )


def save_settings(inst: Installation, form: Form, csrf: str) -> Reply:
    current = inst.file_env()
    # The form sends every field, blank ones included. A blank one clears a
    # value the file holds, and for a key the file does not carry there is
    # nothing to clear - writing `KEY=` for it would only clutter the file.
    submitted = {
        key: value
        for key in EDITABLE_KEYS
        if key in form and ((value := field(form, key)) or key in current)
    }
    # The one setting the server does not refuse: an unknown log level
    # falls back to the default rather than stopping a start. Written from
    # here it would be stored, shown as that default, and never take effect.
    level = submitted.get(LOG_LEVEL_KEY, "")
    if level and level.upper() not in LOG_LEVELS:
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            f"Nicht gespeichert: {LOG_LEVEL_KEY} kennt nur "
            f"{', '.join(LOG_LEVELS)}, nicht {level}.",
            kind="bad",
        )
    # Validated by the same code the server uses, so a value accepted here
    # cannot be one that stops the server from starting later.
    proposed = {**current, **submitted}
    try:
        load_settings(env=proposed)
    except ConfigError as exc:
        # The server's own wording, quoted rather than translated. A German
        # paraphrase here would be a second copy of a rule that lives in
        # settings/, and the two would part company on the first change.
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            f"Nicht gespeichert, der Server würde das ablehnen: {exc}",
            kind="bad",
        )
    try:
        update_env_file(inst.env_path, submitted)
    except (OSError, ValueError) as exc:
        return _page_with(
            inst,
            csrf,
            pages.credentials,
            _write_failed(inst.env_path, exc),
            kind="bad",
        )
    logbook.configui.settings_saved(inst.env_path.name, list(submitted))
    refused = _reloaded(inst)
    return _page_with(
        inst,
        csrf,
        pages.credentials,
        f"{len(submitted)} Einstellungen nach {inst.env_path} geschrieben.{refused}",
        kind="bad" if refused else "good",
    )


def permissions(inst: Installation, form: Form, csrf: str) -> Reply | None:
    """One form, seven buttons: the button's value says which."""
    chosen = [name for name in form.get("tool", []) if name in known_tools()]
    actions: dict[str, Callable[[], Reply]] = {
        "save": lambda: _save_policy(inst, csrf, chosen),
        "load": lambda: _load_profile(inst, csrf, form),
        "profile-save": lambda: _save_profile(inst, csrf, form, chosen),
        "profile-overwrite": lambda: _overwrite_profile(inst, csrf, form, chosen),
        "profile-delete": lambda: _delete_profile(inst, csrf, form),
        "policy-export": lambda: export(inst),
        "policy-import": lambda: _import_policy(inst, csrf, form, chosen),
    }
    action = actions.get(field(form, "action"))
    return None if action is None else action()


def _save_policy(inst: Installation, csrf: str, chosen: list[str]) -> Reply:
    """Write the file. The one action here that changes what a server does."""
    flags = {name: name in chosen for name in known_tools()}
    try:
        inst.policy.save(flags)
    except (OSError, ValueError) as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            _write_failed(inst.policy_path, exc),
            kind="bad",
        )
    writers = sorted(n for n in chosen if known_tools()[n].access == "write")
    logbook.configui.policy_saved(inst.policy_path, len(chosen), len(flags), writers)
    text = f"{len(chosen)} von {len(flags)} Tools aktiv."
    if writers:
        text += (
            f" Davon dürfen {len(writers)} echte Buchhaltungsdaten ändern: "
            + ", ".join(writers)
            + "."
        )
    return _page_with(
        inst, csrf, pages.permissions, text, kind="" if writers else "good"
    )


def _load_profile(inst: Installation, csrf: str, form: Form) -> Reply:
    name = field(form, "profile")
    profile = inst.profiles.get(name)
    if profile is None:
        return _page_with(
            inst, csrf, pages.permissions, f"Kein Profil namens {name}.", kind="bad"
        )
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
    return Reply(
        pages.permissions(
            inst,
            csrf=csrf,
            message=note(esc(text)),
            flags=profile.flags(known),
        )
    )


def _save_profile(
    inst: Installation, csrf: str, form: Form, chosen: list[str]
) -> Reply:
    """Create a profile under a new name, and only under a new one.

    A name that is already taken is refused rather than silently replacing
    what is there. Case and spacing do not distinguish two profiles: "nur
    lesend" beside "Nur lesend" is a duplicate a person cannot tell apart in
    the list, which sorts case-insensitively. Overwriting has a button of its
    own.
    """
    name = field(form, "profile_name")
    clash = inst.profiles.find(name)
    if clash is not None:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            f"Es gibt schon ein Profil namens „{clash.name}“. Oben "
            "auswählen und überschreiben, oder einen anderen Namen nehmen.",
            kind="bad",
            flags=_flags(chosen),
            opened="profiles",
        )
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except ProfileError as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            str(exc),
            kind="bad",
            flags=_flags(chosen),
            opened="profiles",
        )
    except OSError as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            _write_failed(inst.profiles.path, exc),
            kind="bad",
            flags=_flags(chosen),
            opened="profiles",
        )
    logbook.configui.profile_saved(profile.name, len(profile.tools), False)
    return _page_with(
        inst,
        csrf,
        pages.permissions,
        f"Profil {profile.name} angelegt, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        kind="good",
        flags=_flags(chosen),
        opened="profiles",
    )


def _overwrite_profile(
    inst: Installation, csrf: str, form: Form, chosen: list[str]
) -> Reply:
    """Replace the selected profile with what is ticked right now."""
    name = field(form, "profile")
    if inst.profiles.get(name) is None:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            f"Kein Profil namens {name}.",
            kind="bad",
            flags=_flags(chosen),
            opened="profiles",
        )
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except OSError as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            _write_failed(inst.profiles.path, exc),
            kind="bad",
            flags=_flags(chosen),
            opened="profiles",
        )
    logbook.configui.profile_saved(profile.name, len(profile.tools), True)
    return _page_with(
        inst,
        csrf,
        pages.permissions,
        f"Profil {profile.name} überschrieben, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        kind="good",
        flags=_flags(chosen),
        opened="profiles",
    )


def _delete_profile(inst: Installation, csrf: str, form: Form) -> Reply:
    name = field(form, "profile")
    try:
        gone = inst.profiles.delete(name)
    except OSError as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            _write_failed(inst.profiles.path, exc),
            kind="bad",
            opened="profiles",
        )
    if gone:
        logbook.configui.profile_deleted(name)
    return _page_with(
        inst,
        csrf,
        pages.permissions,
        f"Profil {name} gelöscht." if gone else f"Kein Profil namens {name}.",
        kind="good" if gone else "bad",
        opened="profiles",
    )


# --- carrying the policy file ----------------------------------------------


def export(inst: Installation) -> Reply:
    """The policy in effect as a download, written the way a save writes it.

    Not the bytes on disk: a file edited by hand may leave tools out, carry
    names that are no tool, or say ``1`` for ``true``. The download says
    what the server makes of it, one flag for every tool it knows.
    """
    return Reply(
        transfer.dumps(inst.policy.as_map()).encode("utf-8"), download=_EXPORT_NAME
    )


def _import_policy(
    inst: Installation, csrf: str, form: Form, chosen: list[str]
) -> Reply:
    """Read a policy file into the form. Saving is still a separate act.

    The rule is the one `--tools sync` follows: a tool the file does not name
    stays **off**, because that is what an unmentioned tool means everywhere
    else in this project. A file written before a tool existed therefore
    leaves it switched off rather than guessing, and how many those are is
    said out loud instead of being left to be noticed.
    """
    text = field(form, "bundle")
    try:
        arriving = transfer.parse(text)
    except transfer.TransferError as exc:
        return _page_with(
            inst,
            csrf,
            pages.permissions,
            str(exc),
            kind="bad",
            flags=_flags(chosen),
            opened="policy",
        )

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
        text_out += f" Übergangen, weil es sie hier nicht gibt: {', '.join(unknown)}."
    return Reply(
        pages.permissions(
            inst,
            csrf=csrf,
            message=note(esc(text_out)),
            flags=flags,
            opened="policy",
        )
    )


# --- small helpers ---------------------------------------------------------


def _page_with(
    inst: Installation,
    csrf: str,
    render: Callable[..., bytes],
    text: str,
    *,
    kind: str = "",
    flags: dict[str, bool] | None = None,
    opened: str = "",
) -> Reply:
    """A page with one message box on it, the way most actions answer."""
    extra: dict[str, Any] = {}
    if flags is not None:
        extra["flags"] = flags
    if opened:
        extra["opened"] = opened
    return Reply(
        render(inst, csrf=csrf, message=pages.message_box(text, kind), **extra)
    )


def _reloaded(inst: Installation) -> str:
    """Read the settings back after a write, and say it if they are refused.

    What was just written was checked, or is a key or a token. Another value
    in the file, or in the environment, can still be one the server refuses,
    and reading the settings back is where that shows. The write happened,
    so the page says so and quotes the server's reason, rather than the
    request ending without an answer.
    """
    try:
        inst.reload()
    except ConfigError as exc:
        return f" Der Server würde die Einstellungen trotzdem ablehnen: {exc}"
    return ""


def field(form: Form, name: str) -> str:
    """One single-valued field of a form, stripped, empty when absent."""
    return form.get(name, [""])[0].strip()


def _write_failed(path: Path, exc: OSError | ValueError) -> str:
    """Why a file was not written. A refused value is quoted, not translated.

    One sentence for the three files this interface writes. The path is
    shown: this page is read by the person sitting at the machine, who is the
    one who can do something about a directory they do not own.

    Called exactly where a write failed, so it is also where stderr hears of
    it.
    """
    logbook.configui.write_failed(path, exc)
    if isinstance(exc, ValueError):
        return f"Nicht gespeichert: {exc}"
    return f"Konnte {path} nicht schreiben: {exc.strerror or exc}"


def _flags(chosen: list[str]) -> dict[str, bool]:
    return {name: name in chosen for name in known_tools()}
