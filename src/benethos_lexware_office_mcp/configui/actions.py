"""What each form on the three pages does, as plain functions.

An action takes the installation it edits and the submitted form, and
answers with a :class:`Reply`: a page with a message on it, or a file to
download. ``None`` means there is no such action, which the handler answers
as a 404.

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


@dataclasses.dataclass(frozen=True)
class Reply:
    """What an action answers with: a page and its message, or a file.

    A file is ``body`` under the name ``download``, and has no page.
    """

    page: Page | None = None
    message: Message | None = None
    body: bytes = b""
    download: str | None = None


Action = Callable[[Installation, Form], Reply | None]


def check(inst: Installation, form: Form) -> Reply:
    account, text = probe.check(inst.settings)
    message = Message(text, "err") if account is None else Message.found(text, account)
    return Reply(pages.overview(inst), message)


def save_key(inst: Installation, form: Form) -> Reply:
    key = field(form, "api_key")
    skip_check = bool(form.get("unchecked"))
    if not key:
        return _credentials(
            inst, "Kein Schlüssel eingegeben, nichts geändert.", kind="warn"
        )

    try:
        credential(key, name=API_KEY)
    except ConfigError as exc:
        return _refused_by_server(inst, exc)

    verified: probe.Account | None = None
    if not skip_check:
        probe_settings = dataclasses.replace(inst.settings, api_key=key)
        verified, message = probe.check(probe_settings, keep=False)
        if verified is None:
            logbook.configui.key_refused()
            return _credentials(inst, f"Nicht gespeichert. {message}")

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
        inst, f"Schlüssel nach {inst.env_path} geschrieben.{suffix}{shadow}"
    )


def save_bearer(inst: Installation, form: Form) -> Reply:
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
            return _credentials(
                inst,
                "Nicht gespeichert: ein leeres Token wäre kein Token. "
                "Der Server startet den HTTP-Transport dann nicht.",
            )
        try:
            credential(token, name=BEARER_KEY)
        except ConfigError as exc:
            return _refused_by_server(inst, exc)
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
        f"{done} Ein laufender Server übernimmt es beim nächsten Start, "
        f"jeder Client braucht es dann neu.{shadow}",
    )


def save_settings(inst: Installation, form: Form) -> Reply:
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
        return _credentials(
            inst,
            f"Nicht gespeichert: {LOG_LEVEL_KEY} kennt nur "
            f"{', '.join(LOG_LEVELS)}, nicht {level}.",
        )
    # Validated by the same code the server uses, so a value accepted here
    # cannot be one that stops the server from starting later.
    proposed = {**current, **submitted}
    try:
        load_settings(env=proposed)
    except ConfigError as exc:
        return _refused_by_server(inst, exc)
    failed = _write_env(inst, submitted)
    if failed is not None:
        return failed
    logbook.configui.settings_saved(inst.env_path.name, list(submitted))
    return _written(
        inst, f"{len(submitted)} Einstellungen nach {inst.env_path} geschrieben."
    )


def permissions(inst: Installation, form: Form) -> Reply | None:
    """One form, seven buttons: the button's value says which."""
    chosen = [name for name in form.get("tool", []) if name in known_tools()]
    actions: dict[str, Callable[[], Reply]] = {
        "save": lambda: _save_policy(inst, chosen),
        "load": lambda: _load_profile(inst, form),
        "profile-save": lambda: _save_profile(inst, form, chosen),
        "profile-overwrite": lambda: _overwrite_profile(inst, form, chosen),
        "profile-delete": lambda: _delete_profile(inst, form),
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
        return _permissions(inst, _write_failed(inst.policy_path, exc))
    writers = sorted(writing(chosen))
    logbook.configui.policy_saved(inst.policy_path, len(chosen), len(flags), writers)
    text = f"{len(chosen)} von {len(flags)} Tools aktiv."
    if writers:
        text += (
            f" Davon dürfen {len(writers)} echte Buchhaltungsdaten ändern: "
            + ", ".join(writers)
            + "."
        )
    return _permissions(inst, text, kind="warn" if writers else "ok")


def _load_profile(inst: Installation, form: Form) -> Reply:
    name = field(form, "profile")
    profile = inst.profiles.get(name)
    if profile is None:
        return _permissions(inst, f"Kein Profil namens {name}.")
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
    return Reply(pages.permissions(inst, flags=profile.flags(known)), Message(text))


def _save_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
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
        return _permissions(
            inst,
            f"Es gibt schon ein Profil namens „{clash.name}“. Oben "
            "auswählen und überschreiben, oder einen anderen Namen nehmen.",
            chosen=chosen,
            opened="profiles",
        )
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except ProfileError as exc:
        return _permissions(inst, str(exc), chosen=chosen, opened="profiles")
    except OSError as exc:
        return _permissions(
            inst,
            _write_failed(inst.profiles.path, exc),
            chosen=chosen,
            opened="profiles",
        )
    logbook.configui.profile_saved(profile.name, len(profile.tools), False)
    return _permissions(
        inst,
        f"Profil {profile.name} angelegt, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        kind="ok",
        chosen=chosen,
        opened="profiles",
    )


def _overwrite_profile(inst: Installation, form: Form, chosen: list[str]) -> Reply:
    """Replace the selected profile with what is ticked right now."""
    name = field(form, "profile")
    if inst.profiles.get(name) is None:
        return _permissions(
            inst,
            f"Kein Profil namens {name}.",
            chosen=chosen,
            opened="profiles",
        )
    try:
        profile = inst.profiles.save(name, chosen, known_tools())
    except OSError as exc:
        return _permissions(
            inst,
            _write_failed(inst.profiles.path, exc),
            chosen=chosen,
            opened="profiles",
        )
    logbook.configui.profile_saved(profile.name, len(profile.tools), True)
    return _permissions(
        inst,
        f"Profil {profile.name} überschrieben, {len(profile.tools)} Tools. "
        "Die Rechtedatei selbst ist unverändert.",
        kind="ok",
        chosen=chosen,
        opened="profiles",
    )


def _delete_profile(inst: Installation, form: Form) -> Reply:
    name = field(form, "profile")
    try:
        gone = inst.profiles.delete(name)
    except OSError as exc:
        return _permissions(
            inst, _write_failed(inst.profiles.path, exc), opened="profiles"
        )
    if gone:
        logbook.configui.profile_deleted(name)
    return _permissions(
        inst,
        f"Profil {name} gelöscht." if gone else f"Kein Profil namens {name}.",
        kind="ok" if gone else "err",
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
        return _permissions(inst, str(exc), chosen=chosen, opened="policy")

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
        pages.permissions(inst, flags=flags, opened="policy"), Message(text_out)
    )


# --- small helpers ---------------------------------------------------------


def _credentials(inst: Installation, text: str, *, kind: str = "err") -> Reply:
    """The credentials page with one message, a refusal unless said otherwise."""
    return Reply(pages.credentials(inst), Message(text, kind))


def _permissions(
    inst: Installation,
    text: str,
    *,
    kind: str = "err",
    chosen: list[str] | None = None,
    opened: str = "",
) -> Reply:
    """The permissions page with one message, a refusal unless said otherwise.

    ``chosen`` keeps the boxes as they were ticked when the form was sent, so
    an answer about a profile does not undo what somebody had just ticked.
    """
    flags = None if chosen is None else _flags(chosen)
    return Reply(
        pages.permissions(inst, flags=flags, opened=opened), Message(text, kind)
    )


def _refused_by_server(inst: Installation, exc: ConfigError) -> Reply:
    """A value the server would refuse, in the server's own words.

    Quoted rather than translated: a German paraphrase here would be a second
    copy of a rule that lives in settings/, and the two would part company on
    the first change.
    """
    return _credentials(
        inst, f"Nicht gespeichert, der Server würde das ablehnen: {exc}"
    )


def _write_env(inst: Installation, updates: dict[str, str]) -> Reply | None:
    """Write ``updates`` into the ``.env``: ``None``, or the page saying why not."""
    try:
        update_env_file(inst.env_path, updates)
    except (OSError, ValueError) as exc:
        return _credentials(inst, _write_failed(inst.env_path, exc))
    return None


def _written(inst: Installation, text: str) -> Reply:
    """The answer to a write that happened, with the settings read back."""
    refused = _reloaded(inst)
    kind = "err" if refused else "ok"
    return _credentials(inst, f"{text}{refused}", kind=kind)


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
