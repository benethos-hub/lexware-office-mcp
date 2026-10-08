"""What each form on the pages does, as plain functions.

An action takes the installation it edits and the submitted form, and
answers with a :class:`Reply`. ``None`` means there is no such action, which
the handler answers as a 404.

**A form that goes through answers with a redirect** and one message, which
the next page shows once: Post/Redirect/Get, so a reload repeats nothing.
What that page needs beyond the files - the ticks of a loaded profile, the
block to unfold - travels beside the message as ``view``. **A refused form
comes back at once**, with what was typed and the reason at the top, as a
400. A write the operating system refused is a 500, with the same page.

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
from ..policy import known_tools, writing
from ..settings import LOG_LEVELS, load_settings
from ..settings.envfile import update_env_file
from ..settings.parse import credential
from . import pages, probe, transfer
from .pages import Message, Page
from .profiles import Profile, ProfileError
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

# Where each form sends the browser once it went through.
_CREDENTIALS = "/credentials"
_PERMISSIONS = "/permissions"
_SETTINGS = "/settings"
_CHECKED = "/credentials"


@dataclasses.dataclass(frozen=True)
class Reply:
    """What an action answers with.

    Exactly one of three: ``redirect``, the address to go to next, with the
    ``message`` and the ``view`` that page shows once - ``page``, shown at
    once with ``status``, which is how a refusal answers - or ``body``, a
    file to download under the name ``download``.
    """

    redirect: str | None = None
    message: Message | None = None
    view: dict[str, Any] = dataclasses.field(default_factory=dict)
    page: Page | None = None
    status: int = 200
    body: bytes = b""
    download: str | None = None


Action = Callable[[Installation, Form], Reply | None]


def check(inst: Installation, form: Form) -> Reply:
    account, text = probe.check(inst.settings)
    message = Message(text, "err") if account is None else Message.found(text, account)
    return Reply(redirect=_CHECKED, message=message)


def save_key(inst: Installation, form: Form) -> Reply:
    key = field(form, "api_key")
    skip_check = bool(form.get("unchecked"))
    if not key:
        return _done(
            _CREDENTIALS, "Kein Schlüssel eingegeben, nichts geändert.", "warn"
        )

    try:
        credential(key, name=API_KEY)
    except ConfigError as exc:
        return _refused_by_server(pages.credentials(inst), exc)

    verified: probe.Account | None = None
    if not skip_check:
        probe_settings = dataclasses.replace(inst.settings, api_key=key)
        verified, message = probe.check(probe_settings, keep=False)
        if verified is None:
            logbook.configui.key_refused()
            return _refused(pages.credentials(inst), f"Nicht gespeichert. {message}")

    failed = _write_env(inst, {API_KEY: key})
    if failed is not None:
        return failed
    if verified is not None:
        probe.remember(verified)
    logbook.configui.key_saved(inst.env_path.name, verified is not None)
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
    return _written(
        inst,
        _CREDENTIALS,
        f"Schlüssel nach {inst.env_path} geschrieben.{suffix}{shadow}",
    )


def save_bearer(inst: Installation, form: Form) -> Reply:
    """Write the HTTP token, or make one. Never write an empty one.

    Empty means "leave alone" for the API key, where the field is blank by
    design. Here the field shows what is set, so blank can only mean the
    value was cleared - and a cleared token is a server that stops serving on
    its next start.
    """
    typed = {BEARER_KEY: field(form, "bearer")}
    if field(form, "action") == "generate":
        token = secrets.token_urlsafe(32)
        done = "Neues Token erzeugt und gespeichert."
    else:
        token = typed[BEARER_KEY]
        if not token:
            return _refused(
                pages.credentials(inst, typed=typed),
                "Nicht gespeichert: ein leeres Token wäre kein Token. "
                "Der Server startet den HTTP-Transport dann nicht.",
            )
        try:
            credential(token, name=BEARER_KEY)
        except ConfigError as exc:
            return _refused_by_server(pages.credentials(inst, typed=typed), exc)
        done = "Token gespeichert."

    failed = _write_env(inst, {BEARER_KEY: token})
    if failed is not None:
        return failed
    logbook.configui.token_saved(
        inst.env_path.name, field(form, "action") == "generate"
    )
    shadow = (
        " Achtung: eine Umgebungsvariable setzt es weiterhin außer Kraft."
        if inst.shadowed(BEARER_KEY)
        else ""
    )
    return _written(
        inst,
        _CREDENTIALS,
        f"{done} Ein laufender Server übernimmt es beim nächsten Start, "
        f"jeder Client braucht es dann neu.{shadow}",
    )


def save_settings(inst: Installation, form: Form) -> Reply:
    current = inst.file_env()
    # The form sends every field, blank ones included. A blank one clears a
    # value the file holds, and for a key the file does not carry there is
    # nothing to clear - writing `KEY=` for it would only clutter the file.
    # Nor is a field that says what the file says a change.
    submitted = {
        key: value
        for key in EDITABLE_KEYS
        if key in form
        and ((value := field(form, key)) or key in current)
        and value != current.get(key, "").strip()
    }
    if not submitted:
        return _done(_SETTINGS, "Nichts geändert, also nichts geschrieben.")
    typed = {key: field(form, key) for key in EDITABLE_KEYS if key in form}
    # The one setting the server does not refuse: an unknown log level
    # falls back to the default rather than stopping a start. Written from
    # here it would be stored, shown as that default, and never take effect.
    level = submitted.get(LOG_LEVEL_KEY, "")
    if level and level.upper() not in LOG_LEVELS:
        return _refused(
            pages.settings(inst, typed=typed),
            f"Nicht gespeichert: {LOG_LEVEL_KEY} kennt nur "
            f"{', '.join(LOG_LEVELS)}, nicht {level}.",
        )
    # Validated by the same code the server uses, so a value accepted here
    # cannot be one that stops the server from starting later.
    proposed = {**current, **submitted}
    try:
        load_settings(env=proposed)
    except ConfigError as exc:
        return _refused_by_server(pages.settings(inst, typed=typed), exc)
    failed = _write_env(inst, submitted, pages.settings(inst, typed=typed))
    if failed is not None:
        return failed
    logbook.configui.settings_saved(inst.env_path.name, list(submitted))
    count = len(submitted)
    return _written(
        inst,
        _SETTINGS,
        f"{count} {'Einstellung' if count == 1 else 'Einstellungen'} "
        f"nach {inst.env_path} geschrieben.",
    )


def permissions(inst: Installation, form: Form) -> Reply | None:
    """One form, seven buttons: the button's value says which."""
    chosen = [name for name in form.get("tool", []) if name in known_tools()]
    actions: dict[str, Callable[[], Reply]] = {
        "save": lambda: _save_policy(inst, chosen),
        "load": lambda: _load_profile(inst, form, chosen),
        "profile-save": lambda: _save_profile(inst, form, chosen),
        "profile-overwrite": lambda: _overwrite_profile(inst, form, chosen),
        "profile-delete": lambda: _delete_profile(inst, form, chosen),
        "policy-export": lambda: export(inst),
        "policy-import": lambda: _import_policy(inst, form, chosen),
    }
    action = actions.get(field(form, "action"))
    return None if action is None else action()


def _save_policy(inst: Installation, chosen: list[str]) -> Reply:
    """Write the file. The one action here that changes what a server does."""
    flags = _flags(chosen)
    try:
        inst.policy.save(flags)
    except (OSError, ValueError) as exc:
        return _not_written(
            pages.permissions(inst, flags=flags), _write_failed(inst.policy_path, exc)
        )
    writers = sorted(writing(chosen))
    logbook.configui.policy_saved(inst.policy_path, len(chosen), len(flags), writers)
    text = f"{len(chosen)} von {len(flags)} Tools aktiv."
    if writers:
        text += (
            f" Davon dürfen {len(writers)} echte Buchhaltungsdaten ändern: "
            + ", ".join(writers)
            + "."
        )
    return _done(_PERMISSIONS, text, "warn" if writers else "ok")


def _load_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
    name = field(form, "profile")
    profile = inst.profiles.get(name)
    if profile is None:
        return _refused(
            pages.permissions(inst, flags=_flags(chosen), opened="profiles"),
            f"Kein Profil namens {name}.",
        )
    known = list(known_tools())
    newer = profile.newer_tools(known)
    unknown = profile.unknown(known)
    text = (
        f"Profil {profile.name} geladen, {len(profile.tools)} Tools. "
        "Noch nichts geschrieben — dafür oben rechts auf „Rechte speichern“."
    )
    if newer:
        text += (
            f" {len(newer)} Tools sind neuer als das Profil und bleiben "
            "deshalb aus: " + ", ".join(newer) + "."
        )
    if unknown:
        text += f" Übergangen, weil es sie nicht mehr gibt: {', '.join(unknown)}."
    return _done(_PERMISSIONS, text, "warn", flags=profile.flags(known))


def _save_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
    """Create a profile under a new name, and only under a new one.

    A name that is already taken is refused rather than silently replacing
    what is there. Case and spacing do not distinguish two profiles: "nur
    lesend" beside "Nur lesend" is a duplicate a person cannot tell apart in
    the list, which sorts case-insensitively. Overwriting has a button of its
    own.
    """
    name = field(form, "profile_name")
    here = pages.permissions(inst, flags=_flags(chosen), opened="profiles")
    clash = inst.profiles.find(name)
    if clash is not None:
        return _refused(
            here,
            f"Es gibt schon ein Profil namens „{clash.name}“. Oben "
            "auswählen und überschreiben, oder einen anderen Namen nehmen.",
        )
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except ProfileError as exc:
        return _refused(here, str(exc))
    except OSError as exc:
        return _not_written(here, _write_failed(inst.profiles.path, exc))
    logbook.configui.profile_saved(profile.name, len(profile.tools), False)
    return _done(
        _PERMISSIONS,
        f"Profil {profile.name} angelegt, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        flags=_flags(chosen),
        opened="profiles",
    )


def _overwrite_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
    """Replace the selected profile with what is ticked right now."""
    name = field(form, "profile")
    here = pages.permissions(inst, flags=_flags(chosen), opened="profiles")
    if inst.profiles.get(name) is None:
        return _refused(here, f"Kein Profil namens {name}.")
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except OSError as exc:
        return _not_written(here, _write_failed(inst.profiles.path, exc))
    logbook.configui.profile_saved(profile.name, len(profile.tools), True)
    return _done(
        _PERMISSIONS,
        f"Profil {profile.name} überschrieben, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        flags=_flags(chosen),
        opened="profiles",
    )


def _delete_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
    name = field(form, "profile")
    here = pages.permissions(inst, flags=_flags(chosen), opened="profiles")
    try:
        gone = inst.profiles.delete(name)
    except OSError as exc:
        return _not_written(here, _write_failed(inst.profiles.path, exc))
    if not gone:
        return _refused(here, f"Kein Profil namens {name}.")
    logbook.configui.profile_deleted(name)
    return _done(
        _PERMISSIONS,
        f"Profil {name} gelöscht.",
        flags=_flags(chosen),
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
        body=transfer.dumps(inst.policy.as_map()).encode("utf-8"),
        download=_EXPORT_NAME,
    )


def _import_policy(inst: Installation, form: Form, chosen: list[str]) -> Reply:
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
        return _refused(
            pages.permissions(inst, flags=_flags(chosen), opened="policy"), str(exc)
        )

    known = known_tools()
    # Read as a profile that knew exactly the tools the file names: what is
    # on is a flag, and a tool the file does not name is one newer than it,
    # the same question a loaded profile answers.
    imported = Profile(
        name="",
        tools=tuple(name for name, on in arriving.items() if on),
        known=tuple(arriving),
    )
    flags = imported.flags(known)
    newer = imported.newer_tools(known)
    # Every name in the file, on or off, unlike a profile's own question.
    unknown = sorted(name for name in arriving if name not in known)

    on = sum(flags.values())
    text_out = (
        f"Rechtedatei eingelesen, {on} von {len(known)} Tools angehakt. "
        "Geschrieben ist noch nichts — dafür oben rechts auf „Rechte speichern“."
    )
    if newer:
        text_out += (
            f" {len(newer)} Tools nennt die Datei nicht und bleiben "
            "deshalb aus: " + ", ".join(newer) + "."
        )
    if unknown:
        text_out += f" Übergangen, weil es sie hier nicht gibt: {', '.join(unknown)}."
    return _done(_PERMISSIONS, text_out, "warn", flags=flags, opened="policy")


# --- small helpers ---------------------------------------------------------


def _done(address: str, text: str, kind: str = "ok", **view: Any) -> Reply:
    """A form that went through: on to ``address``, with one message."""
    return Reply(redirect=address, message=Message(text, kind), view=view)


def _refused(page: Page, text: str) -> Reply:
    """A form refused, shown again at once with the reason at the top."""
    return Reply(page=page, message=Message(text, "err"), status=400)


def _not_written(page: Page, text: str) -> Reply:
    """A write the operating system refused: the same page, as a 500."""
    return Reply(page=page, message=Message(text, "err"), status=500)


def _refused_by_server(page: Page, exc: ConfigError) -> Reply:
    """A value the server would refuse, in the server's own words.

    Quoted rather than translated: a German paraphrase here would be a second
    copy of a rule that lives in settings/, and the two would part company on
    the first change.
    """
    return _refused(page, f"Nicht gespeichert, der Server würde das ablehnen: {exc}")


def _write_env(
    inst: Installation, updates: dict[str, str], page: Page | None = None
) -> Reply | None:
    """Write ``updates`` into the ``.env``: ``None``, or ``page`` saying why not.

    ``page`` is the one the form came from, the credentials page if not said.
    """
    try:
        update_env_file(inst.env_path, updates)
    except (OSError, ValueError) as exc:
        page = page or pages.credentials(inst)
        text = _write_failed(inst.env_path, exc)
        # A value the file format cannot hold is the form's fault, a
        # directory nobody may write to is not.
        return (
            _refused(page, text)
            if isinstance(exc, ValueError)
            else (_not_written(page, text))
        )
    return None


def _written(inst: Installation, address: str, text: str) -> Reply:
    """The answer to a write that happened, with the settings read back."""
    refused = _reloaded(inst)
    return _done(address, f"{text}{refused}", "err" if refused else "ok")


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
