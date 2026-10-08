"""The four screens, each a function from state to a template and its context.

Rendering is kept apart from serving on purpose: nothing here reads a request,
writes a file or reaches the network, so every page can be rendered in a test
by handing it an installation and reading the HTML back.

A page function computes what its template shows and nothing else. The
template lays it out and decides nothing a function here could pass, and
:meth:`Page.html` puts it into the frame every page shares.

The reading order is the order of the navigation, and the four are named
here as the routes name them, not as the screen labels them: **overview**
(`Übersicht`) answers where this installation stands and which files it
uses, **credentials** (`Zugangsdaten`) is where the key is entered and
tested, **permissions** (`Rechte`) is the point of the whole thing —
including the saved profiles and the policy file itself, which can be
downloaded and read back from there - and **settings** (`Einstellungen`)
holds every setting that is no secret.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..policy import ToolMeta, grouped_tools, known_tools, preset, writing
from ..settings import LOG_LEVELS
from . import templates
from .cost import CHARS_PER_TOKEN, estimate_tokens, tool_costs
from .probe import Account, last_account
from .profiles import Profile
from .state import (
    API_KEY,
    BEARER_KEY,
    CLI_SOURCE,
    ENV_SOURCE,
    LABELS,
    POLICY_KEY,
    Installation,
    defaults,
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
    "settings",
]

# The sidebar, in reading order: (address, label).
NAVIGATION: tuple[tuple[str, str], ...] = (
    ("/", "Übersicht"),
    ("/credentials", "Zugangsdaten"),
    ("/permissions", "Rechte"),
    ("/settings", "Einstellungen"),
)

# The settings page, card by card: a heading, the line beside it, and the
# settings in it. Every editable setting is in exactly one, which a test
# holds, so a setting added to the server cannot go missing from the page.
SETTINGS_CARDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Verbindung",
        "Wohin die Anfragen gehen, wie lange eine dauern darf, wie viele je Sekunde.",
        (
            "LXO_MCP_BASE_URL",
            "LXO_MCP_APP_BASE_URL",
            "LXO_MCP_TIMEOUT",
            "LXO_MCP_RATE",
            "LXO_MCP_BURST",
        ),
    ),
    (
        "Ausgabe",
        "Wie viel eine Antwort an den Assistenten enthält, und was auf stderr steht.",
        ("LXO_MCP_PAGE_SIZE", "LXO_MCP_PDF_PAGES", "LXO_MCP_LOG_LEVEL"),
    ),
    (
        "Dateien",
        "Wo Downloads landen, wie viele bleiben, woher Uploads kommen dürfen.",
        ("LXO_MCP_DOWNLOAD_DIR", "LXO_MCP_KEPT_DOWNLOADS", "LXO_MCP_UPLOAD_DIR"),
    ),
)

LOG_LEVEL_KEY = "LXO_MCP_LOG_LEVEL"

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
    # The one line under the heading that says what the page is for.
    subtitle: str = ""

    def html(self, *, csrf: str = "", message: Message | None = None) -> bytes:
        """The page in its frame, with the session's token and one message."""
        return templates.render(
            self.template,
            title=self.title,
            subtitle=self.subtitle,
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
    """Where this installation stands, what a client needs, which files.

    The card *Stand* has three rows, the key, the permissions and the last
    connection test, each with a tag in a state colour. The first red row is
    the next step, and the page's primary action goes there.
    """
    # Measured first, and not only because the figure is wanted below:
    # building a server is what *defines* the tools, since `classify` runs as
    # each one is registered. Asking `known_tools()` before this returns an
    # empty registry in any process that has not built one.
    costs = tool_costs(inst.settings)
    env = inst.file_env()
    rows = [
        _key_row(inst, env),
        _policy_row(inst, costs),
        _connection_row(),
    ]
    step = next((row["link"] for row in rows if row["tag"]["kind"] == "err"), None)
    return Page(
        "pages/overview.html",
        "Übersicht",
        "/",
        {
            "rows": rows,
            "step": step,
            "files": _files(inst, env),
            "outranked": _outranked(inst),
            "args": _client_arguments(inst),
        },
        "Wo diese Installation steht, was ein Client braucht und welche "
        "Dateien gelten.",
    )


def _stand(
    name: str,
    label: str,
    tag: str,
    kind: str,
    *,
    link: tuple[str, str] | None = None,
    **say: Any,
) -> dict[str, Any]:
    """One row of the card *Stand*: what, its tag, what to read, where to go.

    Every row has every key, so the template asks what a row says rather
    than whether it says it.
    """
    return {
        "name": name,
        "label": label,
        "tag": {"text": tag, "kind": kind},
        "link": link,
        "badge": None,
        "state": "",
        "count": "",
        "spend": "",
        "writers": [],
        "account": "",
        "facts": [],
        **say,
    }


def _key_row(inst: Installation, env: dict[str, str]) -> dict[str, Any]:
    if inst.has_api_key():
        return _stand(
            "key", "API-Schlüssel", "hinterlegt", "ok", badge=_badge(inst, API_KEY, env)
        )
    return _stand(
        "key",
        "API-Schlüssel",
        "fehlt",
        "err",
        link=("/credentials", "Schlüssel eintragen"),
    )


def _policy_row(inst: Installation, costs: dict[str, int]) -> dict[str, Any]:
    """The permissions: how many are on, what they cost, and who may write."""
    policy = inst.policy
    flags = policy.as_map()
    on = [name for name, flag in flags.items() if flag]
    writers = sorted(writing(on))
    count = f"{len(on)} von {len(flags)} Tools aktiv."
    spend = _cost_note(sum(costs.get(name, 0) for name in on))
    link = ("/permissions", "Rechte festlegen")
    if not policy.exists():
        return _stand(
            "policy",
            "Rechte",
            "keine Datei",
            "err",
            link=link,
            state="missing",
            count=count,
        )
    if not on:
        return _stand(
            "policy", "Rechte", "kein Tool", "err", link=link, state="none", count=count
        )
    if writers:
        return _stand(
            "policy",
            "Rechte",
            f"{len(writers)} schreibend",
            "warn",
            state="writers",
            count=count,
            spend=spend,
            writers=writers,
        )
    return _stand(
        "policy", "Rechte", "nur lesend", "ok", state="read", count=count, spend=spend
    )


def _connection_row() -> dict[str, Any]:
    """The last connection test, which only a button runs."""
    account = last_account()
    if account is None:
        return _stand(
            "connection",
            "Verbindung",
            "nicht getestet",
            "",
            link=("/credentials", "Verbindung testen"),
        )
    return _stand(
        "connection",
        "Verbindung",
        "verbunden",
        "ok",
        account=account.label,
        facts=account_facts(account),
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


def _files(inst: Installation, env: dict[str, str]) -> list[dict[str, Any]]:
    """The three files: a name, whether it exists yet, the path to unfold.

    The policy file carries its badge as well, since nobody naming it means
    the search found it, which is worth knowing when it is the wrong one.
    """
    return [
        {
            "label": label,
            "name": path.name,
            "path": str(path),
            "exists": path.is_file(),
            "badge": badge,
        }
        for label, path, badge in (
            ("Einstellungen", inst.env_path, None),
            ("Rechte", inst.policy_path, _badge(inst, POLICY_KEY, env)),
            ("Profile", inst.profiles.path, None),
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
    """The key, the connection test beside it, and the HTTP token.

    ``typed`` is what a refused form held, shown again in place of the file's
    value so nothing has to be typed twice. Never the API key, which no page
    shows.

    The token is folded unless the server is set to an HTTP transport, the
    one case it is for - or a refused form is about it, which would
    otherwise hide the field the reason is about.
    """
    env = inst.file_env()
    shown = {**env, **(typed or {})}
    account = last_account()
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
            "bearer_open": inst.settings.transport != "stdio"
            or BEARER_KEY in (typed or {}),
            "facts": account_facts(account) if account else [],
        },
        "Der API-Schlüssel, die Verbindung zum Konto und das Token für den "
        "HTTP-Transport.",
    )


# --- settings --------------------------------------------------------------


def settings(inst: Installation, *, typed: dict[str, str] | None = None) -> Page:
    """The settings that are no secret, in three cards.

    The placeholder is the built-in default, read the way the value in effect
    is read, because empty means exactly that. A value a real environment
    variable holds is shown and offered as no field: typing over it would
    change nothing, since the variable outranks every file.
    """
    env = inst.file_env()
    shown = {**env, **(typed or {})}
    values = resolved(inst)
    default = defaults()

    def one(key: str) -> dict[str, Any]:
        value = shown.get(key, "")
        choices = None
        if key == LOG_LEVEL_KEY:
            value = value.upper()
            choices = [("", f"Standard ({default[key]})")] + [
                (level, level) for level in LOG_LEVELS
            ]
        return {
            "key": key,
            "label": LABELS[key],
            "badge": _badge(inst, key, env),
            "held": inst.shadowed(key),
            "effective": values[key],
            "value": value,
            "placeholder": default[key],
            "choices": choices,
        }

    return Page(
        "pages/settings.html",
        "Einstellungen",
        "/settings",
        {
            "cards": [
                {"title": title, "meta": meta, "fields": [one(key) for key in keys]}
                for title, meta, keys in SETTINGS_CARDS
            ],
            "env_path": str(inst.env_path),
        },
        "Leer bedeutet: der eingebaute Standard gilt, der Platzhalter zeigt ihn.",
    )


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
            "tools": [_tool_row(name, meta[name], state, costs) for name in names],
        }
        for domain, names in grouped_tools().items()
    ]
    saved = inst.profiles.all()
    # The tally as the page opens, so it is right before the script runs,
    # and without it.
    spend = sum(costs.get(name, 0) for name, on in state.items() if on and name in meta)
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
            "on": sum(1 for name, on in state.items() if on and name in meta),
            "cost": spend,
            "tokens": estimate_tokens(spend),
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
        "Welche Tools der Assistent sieht und aufrufen darf. Nur sie, und nur "
        "das, was die Datei nennt.",
    )


def _tool_row(
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
