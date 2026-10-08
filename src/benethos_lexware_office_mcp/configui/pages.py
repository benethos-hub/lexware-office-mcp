"""The three screens, each a function from state to a template and its context.

Rendering is kept apart from serving on purpose: nothing here reads a request,
writes a file or reaches the network, so every page can be rendered in a test
by handing it an installation and reading the HTML back.

A page function computes what its template shows and nothing else. The
template lays it out and decides nothing a function here could pass, and
:meth:`Page.html` puts it into the frame every page shares.

The reading order is the order of the navigation, and the three are named
here as the routes name them, not as the screen labels them: **overview**
(`Übersicht`) answers what this installation is and which files it uses,
**credentials** (`Zugangsdaten`) is where the key and the settings are
entered, and **permissions** (`Rechte`) is the point of the whole thing —
including the saved profiles and the policy file itself, which can be
downloaded and read back from there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..policy import ToolMeta, grouped_tools, known_tools, preset, writing
from ..settings import DEFAULT_APP_BASE_URL, DEFAULT_BASE_URL, Settings
from . import templates
from .cost import CHARS_PER_TOKEN, estimate_tokens, tool_costs
from .probe import Account, last_account
from .profiles import Profile
from .state import (
    API_KEY,
    BEARER_KEY,
    CLI_SOURCE,
    EDITABLE_KEYS,
    ENV_SOURCE,
    LABELS,
    SETTING_KEYS,
    Installation,
    downloads_dir,
    resolved,
)

__all__ = [
    "NAVIGATION",
    "Badge",
    "Message",
    "Page",
    "account_facts",
    "credentials",
    "error",
    "overview",
    "permissions",
]

# The sidebar, in reading order: (address, label).
NAVIGATION: tuple[tuple[str, str], ...] = (
    ("/", "Übersicht"),
    ("/credentials", "Zugangsdaten"),
    ("/permissions", "Rechte"),
)

# A domain is an identifier in the code and a heading on the screen, and the
# two want different words. An unmapped domain shows its own name rather than
# nothing, so a group added later is visible before this table catches up.
GROUP_LABELS: dict[str, str] = {
    "articles": "Artikel",
    "contacts": "Kontakte",
    "diagnostics": "Diagnose",
    "files": "Dateien",
    "master_data": "Stammdaten",
    "sales_documents": "Verkaufsbelege",
    "vouchers": "Buchhaltungsbelege",
}

# What the API cannot take back, and what that actually means for the record.
# **Neither of these says "gone forever", and neither says "bound now".**
# Nothing this API creates is festgeschrieben at the moment it is created: a
# voucher stays editable, and a sales document is a draft unless the call asks
# for `finalize`. See SPECS.md section 5.
PERMANENCE_LABELS: dict[str, tuple[str, str]] = {
    "app": (
        "nur App",
        "Die API nimmt das nicht zurück. In Lexware Office selbst lässt sich "
        "ein Kontakt ohne Weiteres löschen.",
    ),
    "books": (
        "nur App · Buchhaltung",
        "Die API nimmt das nicht zurück. Beim Anlegen ist nichts "
        "festgeschrieben - in der Web-App löschbar, solange der Beleg nicht "
        "festgeschrieben, mit einer Zahlung verknüpft, weiterverarbeitet oder "
        "exportiert ist. Ab dem Festschreiben bleibt er stehen, § 146 AO.",
    ),
}


@dataclass(frozen=True, slots=True)
class Message:
    """The one line at the top of a page that answers the last action.

    ``kind`` is ``ok``, ``err`` or ``warn``, the three state colours.
    ``account`` and ``facts`` are what a connection test learned, the name
    in bold after the text and the rest after it.
    """

    text: str
    kind: str = "warn"
    account: str = ""
    facts: tuple[str, ...] = ()

    @classmethod
    def found(cls, text: str, account: Account) -> Message:
        """A connection test that went through, and whose account it opened."""
        return cls(text, "ok", account.label, tuple(account_facts(account)))


@dataclass(frozen=True, slots=True)
class Badge:
    """Where a displayed value came from.

    ``detail`` becomes the tooltip, which is where a full path belongs: it
    answers "which file?" for the one person who asks, without putting a
    hundred characters of Windows path into every row.
    """

    source: str
    detail: str = ""

    @property
    def loud(self) -> bool:
        """Marked when the file lost: something outranks what is typed here."""
        return self.source in (ENV_SOURCE, CLI_SOURCE)


@dataclass(frozen=True)
class Page:
    """A template, the heading it shows, and what it needs to fill it."""

    template: str
    title: str
    here: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def html(self, *, csrf: str = "", message: Message | None = None) -> bytes:
        """The page in its frame, with the session's token and one message."""
        return templates.render(
            self.template,
            title=self.title,
            here=self.here,
            navigation=NAVIGATION,
            account=last_account(),
            csrf=csrf,
            message=message,
            **self.context,
        )


def error(title: str, text: str) -> Page:
    """A page that is only a reason: not found, refused, unreadable."""
    return Page("pages/error.html", title, context={"text": text})


def account_facts(account: Account) -> list[str]:
    """What a successful connection test learned, after the company name."""
    bits: list[str] = []
    if account.tax_type:
        bits.append(f"Steuerart: {account.tax_type}")
    if account.small_business is not None:
        bits.append(
            "Kleinunternehmer" if account.small_business else "kein Kleinunternehmer"
        )
    return bits


# --- small pieces ----------------------------------------------------------


def _badge(inst: Installation, key: str, env: dict[str, str]) -> Badge:
    return Badge(inst.source_of(key, env), inst.source_detail(key, env))


def _cost_note(characters: int) -> str:
    return (
        f"{templates.de(characters)} Zeichen, rund "
        f"{templates.de(estimate_tokens(characters))} Token"
    )


# --- overview --------------------------------------------------------------


def overview(inst: Installation) -> Page:
    """What this installation is, which files it reads, and what it may do."""
    # Measured first, and not only because the figure is wanted below:
    # building a server is what *defines* the tools, since `classify` runs as
    # each one is registered. Asking `known_tools()` before this returns an
    # empty registry in any process that has not built one.
    costs = tool_costs(inst.settings)
    values = resolved(inst)
    # The file once, for the whole table, rather than once per row.
    env = inst.file_env()
    rows = [
        {
            "label": LABELS[key],
            "key": key,
            "value": values[key],
            "badge": _badge(inst, key, env),
        }
        for key in SETTING_KEYS
    ]

    policy = inst.policy
    flags = policy.as_map()
    on = [name for name, flag in flags.items() if flag]
    writers = sorted(writing(on))
    if not policy.exists():
        state = "missing"
    elif not on:
        state = "none"
    elif writers:
        state = "writers"
    else:
        state = "read"

    return Page(
        "pages/overview.html",
        "Übersicht",
        "/",
        {
            "rows": rows,
            "on": len(on),
            "total": len(flags),
            "spend": _cost_note(sum(costs.get(name, 0) for name in on)),
            "policy_state": state,
            "policy_path": str(policy.path),
            "writers": writers,
            "files": _files(inst),
            "outranked": _outranked(inst),
            "args": _client_arguments(inst),
        },
    )


def _client_arguments(inst: Installation) -> str:
    """The client entry that would make the server use these same files.

    Both processes pick their files when they start, and this one cannot see
    the arguments the other was given. It can only say which files it is
    working on — so it says them in the form they have to be pasted in.
    Without that, a client started with ``--tools-file`` leaves this page
    editing a different file and reporting success.
    """
    return json.dumps(
        ["--env-file", str(inst.env_path), "--tools-file", str(inst.policy_path)],
        ensure_ascii=False,
    )


def _files(inst: Installation) -> list[dict[str, Any]]:
    """The three files, each with its label, its path and whether it exists."""
    return [
        {"label": label, "code": code, "path": str(path), "exists": path.is_file()}
        for label, code, path in (
            ("Einstellungen", ".env", inst.env_path),
            ("Rechte", "", inst.policy_path),
            ("Profile", "", inst.profiles.path),
        )
    ]


def _outranked(inst: Installation) -> str:
    """The ``.env`` a server would read instead, or nothing.

    A `.env` does not combine with the ones below it, so a higher one does
    not shade a value here - it replaces the file entirely. Said beside the
    paths, because saving would otherwise report success and change nothing
    about the server.
    """
    outranked = inst.outranked_by()
    return "" if outranked is None else str(outranked)


# --- credentials -----------------------------------------------------------


def credentials(inst: Installation, *, typed: dict[str, str] | None = None) -> Page:
    """Where the key is entered, and the settings that are not secret.

    ``typed`` is what a refused form held, shown again in place of the file's
    values so nothing has to be typed twice. Never the API key, which no
    page shows.
    """
    env = inst.file_env()
    shown = {**env, **(typed or {})}
    values = resolved(inst)
    fields = [
        {
            "key": key,
            "label": LABELS[key],
            "badge": _badge(inst, key, env),
            "value": shown.get(key, ""),
            "placeholder": _placeholder(key, values),
        }
        for key in EDITABLE_KEYS
    ]
    return Page(
        "pages/credentials.html",
        "Zugangsdaten",
        "/credentials",
        {
            "has_key": inst.has_api_key(),
            "key_badge": _badge(inst, API_KEY, env),
            "key_shadowed": inst.shadowed(API_KEY),
            "env_path": str(inst.env_path),
            "bearer_key": BEARER_KEY,
            "bearer": shown.get(BEARER_KEY, ""),
            "bearer_badge": _badge(inst, BEARER_KEY, env),
            "fields": fields,
        },
    )


def _placeholder(key: str, values: dict[str, str]) -> str:
    """What an empty field means: the built-in default, or what applies now."""
    defaults = {
        "LXO_MCP_BASE_URL": DEFAULT_BASE_URL,
        "LXO_MCP_APP_BASE_URL": DEFAULT_APP_BASE_URL,
        "LXO_MCP_DOWNLOAD_DIR": downloads_dir(Settings(), unresolved=""),
    }
    if key in defaults:
        return defaults[key]
    return values.get(key, "")


# --- permissions -----------------------------------------------------------


def permissions(
    inst: Installation,
    *,
    flags: dict[str, bool] | None = None,
    opened: str = "",
) -> Page:
    """One checkbox per tool, what it costs, and the saved profiles.

    ``flags`` overrides what the file says, which is how a loaded profile
    fills the form without anything being written yet. ``opened`` names the
    folded block to show unfolded, so an action's answer arrives beside the
    controls it is about: a refusal that hid the field it is about would be
    the worst of both.

    With no policy file at all the boxes open on **read-only** rather than on
    nothing. A blank form is a poor starting point for a decision, and this
    is a suggestion in a form, not a permission: no file means no tools until
    somebody presses save, exactly as before. The page says so at the top,
    because ticks that do not describe the file have to be labelled.
    """
    # Before `known_tools()`, for the reason given in `overview`.
    costs = tool_costs(inst.settings)
    meta = known_tools()
    fresh = not inst.policy.exists()
    if flags is not None:
        state = flags
    elif fresh:
        state = preset("read-only")
    else:
        state = inst.policy.as_map()

    groups = [
        {
            "domain": domain,
            "label": GROUP_LABELS.get(domain, domain),
            "tools": [_row(name, meta[name], state, costs) for name in names],
        }
        for domain, names in grouped_tools().items()
    ]
    saved = inst.profiles.all()
    return Page(
        "pages/permissions.html",
        "Rechte",
        "/permissions",
        {
            # The suggestion is named only where it is what the boxes show.
            # A loaded profile or an imported file ticks its own tools.
            "fresh": fresh,
            "suggested": fresh and flags is None,
            "policy_path": str(inst.policy_path),
            "policy_exists": not fresh,
            "groups": groups,
            "total": len(meta),
            "per_token": CHARS_PER_TOKEN,
            "profiles": [
                {
                    "name": name,
                    "count": len(profile.tools),
                    "saved": _saved_at(profile),
                }
                for name, profile in saved.items()
            ],
            # What the folded summary still has to say.
            "profiles_meta": f"— {len(saved)} gespeichert" if saved else "— noch keine",
            "open_profiles": opened == "profiles",
            "open_policy": opened == "policy",
            "permanence": {
                kind: {"text": text, "title": title}
                for kind, (text, title) in PERMANENCE_LABELS.items()
            },
        },
    )


def _row(
    name: str, info: ToolMeta, state: dict[str, bool], costs: dict[str, int]
) -> dict[str, Any]:
    """One tool as its row shows it: the box, the marks and the cost."""
    if info.access == "read":
        tag = {"text": "lesend", "kind": "accent"}
    else:
        tag = {
            "text": f"schreibend · {info.effect}",
            "kind": "err" if info.irreversible else "warn",
        }
    return {
        "name": name,
        "checked": bool(state.get(name)),
        "read": info.access == "read",
        "destructive": info.irreversible,
        "tag": tag,
        "permanence": info.permanence if info.permanence in PERMANENCE_LABELS else "",
        "cost": costs.get(name, 0),
    }


def _saved_at(profile: Profile) -> str:
    """The tooltip on a profile: when it was written, if it says."""
    return f"gespeichert: {profile.saved}" if profile.saved else "ohne Zeitstempel"
