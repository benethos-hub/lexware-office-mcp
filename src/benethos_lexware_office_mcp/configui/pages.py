"""The three screens, each a function from state to bytes.

Rendering is kept apart from serving on purpose: nothing here reads a request,
writes a file or reaches the network, so every page can be rendered in a test
by handing it an installation and reading the HTML back.

The reading order is the order of the navigation. **Übersicht** answers what
this installation is and which files it uses, **Zugangsdaten** is where the
key and the settings are entered, and **Rechte** is the point of the whole
thing — including the saved profiles, which can be carried to another
installation from there.
"""

from __future__ import annotations

import json

from ..config import (
    DEFAULT_APP_BASE_URL,
    DEFAULT_BASE_URL,
    download_dir,
)
from ..policy import ToolMeta, grouped_tools, known_tools, preset
from .cost import CHARS_PER_TOKEN, estimate_tokens, tool_costs
from .probe import Account, last_account
from .profiles import Profile
from .render import esc, note, page, source_badge
from .state import API_KEY, EDITABLE_KEYS, SETTING_KEYS, Installation

__all__ = ["credentials", "overview", "permissions"]

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

_SETTING_LABELS: dict[str, str] = {
    "LXO_MCP_API_KEY": "API-Schlüssel",
    "LXO_MCP_BASE_URL": "API-Adresse",
    "LXO_MCP_APP_BASE_URL": "Web-App für Deeplinks",
    "LXO_MCP_TOOL_POLICY": "Rechtedatei",
    "LXO_MCP_DOWNLOAD_DIR": "Downloads",
    "LXO_MCP_TIMEOUT": "Zeitlimit je Anfrage (s)",
    "LXO_MCP_RATE": "Anfragen pro Sekunde",
    "LXO_MCP_BURST": "Burst",
    "LXO_MCP_PAGE_SIZE": "Zeilen je Seite",
    "LXO_MCP_PDF_PAGES": "PDF-Seiten je Ansicht",
    "LXO_MCP_LOG_LEVEL": "Protokollstufe",
}

# What the API cannot take back, and what that actually means for the record.
# **Neither of these says "gone forever", and neither says "bound now".**
# Nothing this API creates is festgeschrieben at the moment it is created: a
# voucher stays editable, and a sales document is a draft unless the call asks
# for `finalize`. See SPECS.md section 5.
_PERMANENCE_LABELS: dict[str, tuple[str, str]] = {
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


# --- small pieces ----------------------------------------------------------


def _csrf(token: str) -> str:
    return f'<input type="hidden" name="_csrf" value="{esc(token)}">'


def _de(number: float) -> str:
    """A number the way it is read here: 50.630 rather than 50,630."""
    return f"{number:,.0f}".replace(",", ".")


def _chip(account: Account | None) -> str:
    return f"Konto: {account.label}" if account else ""


def _tag(meta: ToolMeta) -> str:
    if meta.access == "read":
        return '<span class="tag read">lesend</span>'
    css = "del" if meta.irreversible else "write"
    return f'<span class="tag {css}">schreibend · {esc(meta.effect)}</span>'


def _permanence(meta: ToolMeta) -> str:
    if meta.permanence not in _PERMANENCE_LABELS:
        return ""
    return _permanence_badge(meta.permanence)


def _cost_note(characters: int) -> str:
    return f"{_de(characters)} Zeichen, rund {_de(estimate_tokens(characters))} Token"


# --- Übersicht -------------------------------------------------------------


def _resolved(inst: Installation) -> dict[str, str]:
    """What each setting actually is in this process, not what a file says."""
    settings = inst.settings
    return {
        "LXO_MCP_API_KEY": "gesetzt" if settings.api_key else "nicht gesetzt",
        "LXO_MCP_BASE_URL": settings.base_url,
        "LXO_MCP_APP_BASE_URL": settings.app_base_url,
        "LXO_MCP_TOOL_POLICY": str(settings.policy_file()),
        "LXO_MCP_DOWNLOAD_DIR": str(settings.download_path or download_dir()),
        "LXO_MCP_TIMEOUT": f"{settings.timeout:g}",
        "LXO_MCP_RATE": f"{settings.rate:g}",
        "LXO_MCP_BURST": str(settings.burst),
        "LXO_MCP_PAGE_SIZE": str(settings.page_size),
        "LXO_MCP_PDF_PAGES": str(settings.pdf_pages),
        "LXO_MCP_LOG_LEVEL": settings.log_level,
    }


def overview(inst: Installation, *, csrf: str = "", message: str = "") -> bytes:
    """What this installation is, which files it reads, and what it may do."""
    # Measured first, and not only because the figure is wanted below:
    # building a server is what *defines* the tools, since `classify` runs as
    # each one is registered. Asking `known_tools()` before this returns an
    # empty registry in any process that has not built one.
    costs = tool_costs(inst.settings)
    resolved = _resolved(inst)
    rows = "".join(
        f"<tr><td>{esc(_SETTING_LABELS.get(key, key))}<br>"
        f"<code>{esc(key)}</code></td>"
        f"<td>{esc(resolved[key])}</td>"
        f"<td>{source_badge(inst.source_of(key), inst.source_detail(key))}</td></tr>"
        for key in SETTING_KEYS
    )

    policy = inst.policy
    flags = policy.as_map()
    meta = known_tools()
    on = [name for name, flag in flags.items() if flag]
    writers = [name for name in on if meta[name].access == "write"]
    spend = sum(costs.get(name, 0) for name in on)

    if not policy.exists():
        permissions_note = note(
            "Es gibt noch keine Rechtedatei unter "
            f"<code>{esc(str(policy.path))}</code>, also bietet der Server "
            "<strong>kein einziges Tool</strong> an. "
            "Das ist der richtige Zustand, solange niemand entschieden hat — "
            '<a href="/permissions">unter Rechte</a> wird die Datei angelegt.'
        )
    elif not on:
        permissions_note = note(
            "Die Rechtedatei ist da, schaltet aber <strong>kein einziges "
            "Tool</strong> frei. Der Assistent sieht damit nichts von diesem "
            'Konto — <a href="/permissions">unter Rechte</a> auswählen, was '
            "er dürfen soll."
        )
    elif writers:
        permissions_note = note(
            f"<strong>{len(writers)} der {len(on)} aktiven Tools dürfen echte "
            "Buchhaltungsdaten verändern:</strong> "
            + ", ".join(f"<code>{esc(name)}</code>" for name in sorted(writers))
            + "."
        )
    else:
        permissions_note = note(
            f"{len(on)} von {len(flags)} Tools aktiv, alle nur lesend.", "good"
        )

    account = last_account()
    body = f"""
{message}
<h2>Verbindung</h2>
<form method="post" action="/check">{_csrf(csrf)}
  <p><button type="submit">Verbindung testen</button>
  <span class="hint">Ein Aufruf von <code>GET /v1/profile</code>. Nur auf
  Knopfdruck — diese Seite spricht von sich aus nie mit der API.</span></p>
</form>

<h2>Rechte</h2>
<p>{len(on)} von {len(flags)} Tools aktiv. Sie kosten den Assistenten
   {_cost_note(spend)} in jedem einzelnen Gespräch.</p>
{permissions_note}

<h2>Einstellungen</h2>
<p class="hint">Eine echte Umgebungsvariable schlägt jede Datei. Der Wert in
   der Spalte ist der, der tatsächlich gilt.</p>
<table><tr><th>Einstellung</th><th>Wert</th><th>Herkunft</th></tr>
{rows}</table>

<h2>Dateien</h2>
{_files_table(inst)}
"""
    return page("Übersicht", body, here="/", chip=_chip(account))


def _files_table(inst: Installation) -> str:
    policy_path = inst.settings.policy_file()
    rows = [
        ("Einstellungen (<code>.env</code>)", inst.env_path),
        ("Rechte", policy_path),
        ("Profile", inst.profiles.path),
    ]
    cells = "".join(
        f"<tr><td>{label}</td><td><code>{esc(str(path))}</code></td>"
        f"<td>{'vorhanden' if path.is_file() else 'noch nicht angelegt'}</td></tr>"
        for label, path in rows
    )
    return f"<table><tr><th>Datei</th><th>Pfad</th><th>Zustand</th></tr>{cells}</table>"


# --- Zugangsdaten ----------------------------------------------------------


def credentials(inst: Installation, *, csrf: str = "", message: str = "") -> bytes:
    """Where the key is entered, and the settings that are not secret."""
    has_key = inst.has_api_key()
    source = inst.source_of(API_KEY)
    shadowed = inst.shadowed(API_KEY)

    warning = ""
    if shadowed:
        warning = note(
            "Der Schlüssel steht in einer echten Umgebungsvariablen. Die "
            "schlägt jede Datei, ein hier gespeicherter Wert bliebe also ohne "
            "Wirkung, solange sie gesetzt ist."
        )

    fields = "".join(
        f'<label class="fld">{esc(_SETTING_LABELS.get(key, key))} '
        f"<code>{esc(key)}</code> "
        f"{source_badge(inst.source_of(key), inst.source_detail(key))}</label>"
        f'<input type="text" name="{esc(key)}" '
        f'value="{esc(inst.file_env().get(key, ""))}" '
        f'placeholder="{esc(_placeholder(inst, key))}">'
        for key in EDITABLE_KEYS
    )

    body = f"""
{message}
{warning}
<p>Der Schlüssel wird nach <code>{esc(str(inst.env_path))}</code> geschrieben.
   Er wird nie angezeigt, nie protokolliert und geht in keinen Export mit.</p>
<p>Zustand: <strong>{"hinterlegt" if has_key else "nicht hinterlegt"}</strong>
   {source_badge(source, inst.source_detail(API_KEY)) if has_key else ""}</p>

<form method="post" action="/credentials">{_csrf(csrf)}
  <label class="fld" for="api_key">API-Schlüssel</label>
  <input type="password" id="api_key" name="api_key" autocomplete="off"
         placeholder="{"unverändert lassen" if has_key else "hier einfügen"}">
  <p class="hint">In Lexware Office unter Erweiterungen, Public API zu
     erzeugen. Leer lassen ändert nichts.</p>
  <p><label><input type="checkbox" name="unchecked" value="1">
     Ohne Prüfung speichern</label>
     <span class="hint">Sonst wird der Schlüssel erst gegen die API geprüft
     und nur bei Erfolg geschrieben.</span></p>
  <p><button type="submit">Schlüssel speichern</button></p>
</form>

<h2>Einstellungen</h2>
<p class="hint">Leer bedeutet: der eingebaute Standard gilt. Der Platzhalter
   zeigt ihn. Die Rechtedatei steht bewusst nicht hier — welche gemeint ist,
   entscheidet der Aufruf, und sie zu wechseln würde dieser Oberfläche den
   Boden unter den Füßen wegziehen.</p>
<form method="post" action="/settings">{_csrf(csrf)}
  {fields}
  <p><button type="submit">Einstellungen speichern</button></p>
</form>
"""
    return page("Zugangsdaten", body, here="/credentials", chip=_chip(last_account()))


def _placeholder(inst: Installation, key: str) -> str:
    defaults = {
        "LXO_MCP_BASE_URL": DEFAULT_BASE_URL,
        "LXO_MCP_APP_BASE_URL": DEFAULT_APP_BASE_URL,
        "LXO_MCP_DOWNLOAD_DIR": str(download_dir()),
    }
    if key in defaults:
        return defaults[key]
    return _resolved(inst).get(key, "")


# --- Rechte ----------------------------------------------------------------


def permissions(
    inst: Installation,
    *,
    csrf: str = "",
    message: str = "",
    flags: dict[str, bool] | None = None,
) -> bytes:
    """One checkbox per tool, what it costs, and the saved profiles.

    ``flags`` overrides what the file says, which is how a loaded profile
    fills the form without anything being written yet.

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

    if fresh:
        message += note(
            "Es gibt noch keine Rechtedatei, <strong>aktiv ist also "
            "nichts</strong>. Vorgeschlagen und angehakt sind die lesenden "
            "Tools. Erst „Rechte speichern“ legt die Datei an."
        )

    blocks = []
    for domain, names in grouped_tools().items():
        rows = []
        for name in names:
            info = meta[name]
            checked = " checked" if state.get(name) else ""
            rows.append(
                f'<div class="tool">'
                f'<input type="checkbox" name="tool" value="{esc(name)}" '
                f'id="{esc(name)}"{checked}>'
                f'<label for="{esc(name)}"><code>{esc(name)}</code></label>'
                f"{_tag(info)}{_permanence(info)}"
                f'<span class="cost">{_de(costs.get(name, 0))} Z.</span>'
                f"</div>"
            )
        label = GROUP_LABELS.get(domain, domain)
        blocks.append(
            f'<div class="grp" data-group="{esc(domain)}">'
            f"<h3>{esc(label)}"
            f'<span class="acts">'
            f'<button type="button" data-act="grp-on">alle an</button> '
            f'<button type="button" data-act="grp-off">alle aus</button> '
            f'<button type="button" data-act="grp-read">nur lesend</button>'
            f"</span></h3>{''.join(rows)}</div>"
        )

    total = len(meta)
    read_names = sorted(n for n, m in meta.items() if m.access == "read")
    keep_names = sorted(n for n, m in meta.items() if m.irreversible)
    body = f"""
{message}
<p>Nur aktivierte Tools sieht der Assistent überhaupt, und nur sie kann er
   aufrufen. Ein Tool, das die Datei nicht nennt, ist aus. Änderungen wirken
   sofort, der Client muss die Liste allerdings neu abfragen — Claude Desktop
   dafür über das Taskleistensymbol beenden und neu starten.</p>
<p class="hint">Geschrieben wird nach
   <code>{esc(str(inst.settings.policy_file()))}</code>.</p>

<form method="post" action="/permissions" id="permform">{_csrf(csrf)}
  {_profile_bar(inst)}
  {_legend()}
  <p>
    <button type="button" data-act="all-on">alles an</button>
    <button type="button" data-act="all-off">alles aus</button>
    <button type="button" data-act="all-read">nur lesend</button>
    <button type="button" data-act="all-reversible">schreibend ohne löschen</button>
  </p>
  {"".join(blocks)}
  <div class="bar">
    <button type="submit" name="action" value="save">Rechte speichern</button>
    <span><strong><span id="count">–</span> von {total}</strong> aktiv</span>
    <span class="hint"><span id="cost">–</span> Zeichen Kontext,
      rund <span id="tokens">–</span> Token je Anfrage</span>
  </div>
</form>
<script>
(function () {{
  var COST = {json.dumps(costs, separators=(",", ":"))};
  var READ = {json.dumps(read_names, separators=(",", ":"))};
  var DESTRUCTIVE = {json.dumps(keep_names, separators=(",", ":"))};
  var PER_TOKEN = {json.dumps(CHARS_PER_TOKEN)};
  var form = document.getElementById('permform');
  function boxes(root) {{
    return Array.prototype.slice.call(
      (root || form).querySelectorAll('input[name=tool]'));
  }}
  function de(n) {{ return n.toLocaleString('de-DE'); }}
  function refresh() {{
    var on = boxes(form).filter(function (c) {{ return c.checked; }});
    var chars = on.reduce(
      function (sum, c) {{ return sum + (COST[c.value] || 0); }}, 0);
    document.getElementById('count').textContent = on.length;
    document.getElementById('cost').textContent = de(chars);
    document.getElementById('tokens').textContent = de(Math.round(chars / PER_TOKEN));
  }}
  function apply(mode, scope) {{
    boxes(scope).forEach(function (c) {{
      if (mode === 'on') c.checked = true;
      else if (mode === 'off') c.checked = false;
      else if (mode === 'read') c.checked = READ.indexOf(c.value) !== -1;
      else if (mode === 'reversible') c.checked = DESTRUCTIVE.indexOf(c.value) === -1;
    }});
    refresh();
  }}
  document.addEventListener('click', function (e) {{
    var b = e.target && e.target.closest ? e.target.closest('button[data-act]') : null;
    if (!b) return;
    e.preventDefault();
    var act = b.getAttribute('data-act');
    var scoped = act.indexOf('grp-') === 0;
    apply(act.replace(/^(all-|grp-)/, ''), scoped ? b.closest('.grp') : form);
  }});
  document.addEventListener('change', function (e) {{
    if (e.target && e.target.name === 'tool') refresh();
  }});
  refresh();
}})();
</script>
"""
    return page("Rechte", body, here="/permissions", chip=_chip(last_account()))


def _legend() -> str:
    """What the marks on each row mean, on the page rather than in a tooltip.

    A tooltip is a poor place for the one distinction this page exists to
    make. The badges are rendered here with the same markup they carry in the
    list, so the legend cannot drift into describing a different colour.
    """
    return f"""
<div class="grp">
  <h3>Was die Marken bedeuten</h3>
  <p class="hint">
    <span class="tag read">lesend</span> fragt nur ab.
    <span class="tag write">schreibend · create</span> legt an oder ändert.
    <span class="tag del">schreibend · delete</span> entfernt einen Datensatz —
    das kann genau ein Tool, <code>delete_article</code>, und ein Artikel
    lässt sich danach neu anlegen.
  </p>
  <p class="hint">
    {_permanence_badge("app")} die API nimmt das nicht zurück, Lexware Office
    selbst löscht es ohne Weiteres. Betrifft nur Kontakte.
  </p>
  <p class="hint">
    {_permanence_badge("books")} geht in die Buchhaltung. <strong>Beim
    Anlegen ist nichts festgeschrieben</strong> — ein Beleg bleibt änderbar,
    ein Verkaufsbeleg entsteht als Entwurf, solange die Anfrage nicht
    <code>finalize</code> setzt. Gelöscht wird in der Web-App, solange nichts
    ihn bindet: nicht festgeschrieben, keine Zahlung zugeordnet, keine
    Folgedokumente, nicht exportiert. Erst ab dem Festschreiben bleibt er
    stehen, § 146 AO, und korrigiert wird mit einer Storno-Buchung.
  </p>
</div>
"""


def _permanence_badge(kind: str) -> str:
    text, title = _PERMANENCE_LABELS[kind]
    return f'<span class="tag keep" title="{esc(title)}">{esc(text)}</span>'


def _saved_at(profile: Profile) -> str:
    """The tooltip on a profile: when it was written, if it says."""
    return f"gespeichert: {profile.saved}" if profile.saved else "ohne Zeitstempel"


def _profile_bar(inst: Installation) -> str:
    saved = inst.profiles.all()
    if saved:
        options = "".join(
            f'<option value="{esc(name)}" title="{esc(_saved_at(profile))}">'
            f"{esc(name)} ({len(profile.tools)} Tools)</option>"
            for name, profile in saved.items()
        )
        chooser = (
            f'<div class="grow"><label class="fld">Gespeichertes Profil</label>'
            f'<select name="profile">{options}</select></div>'
            '<button type="submit" name="action" value="load">Laden</button>'
            '<button type="submit" name="action" value="profile-delete">'
            "Löschen</button>"
        )
    else:
        chooser = (
            '<div class="grow"><p class="hint">Noch keine Profile gespeichert. '
            "Die Auswahl unten benennen und sichern, dann steht sie hier zur "
            "Auswahl.</p></div>"
        )
    return f"""
<div class="grp">
  <h3>Profile</h3>
  <p class="hint">Ein Profil ist eine benannte Auswahl, keine zweite
     Rechtedatei. Laden füllt nur die Haken — geschrieben wird erst mit
     „Rechte speichern".</p>
  <div class="row">
    {chooser}
  </div>
  <div class="row" style="margin-top:.6rem">
    <div class="grow"><label class="fld">Aktuelle Auswahl sichern als</label>
      <input type="text" name="profile_name" maxlength="60"
             placeholder="z. B. Steuerberater, nur lesend"></div>
    <button type="submit" name="action" value="profile-save">Profil sichern</button>
  </div>
  {_profile_transfer(bool(saved))}
</div>
"""


def _profile_transfer(has_profiles: bool) -> str:
    """Carrying the profiles to another installation, and back.

    Folded away behind a summary: it is the rarest thing on this page, and a
    textarea sitting open would push the tool list off the screen. Only the
    profiles travel - see `transfer.py` for why the settings do not.
    """
    export = (
        '<p><button type="submit" name="action" value="profile-export">'
        "Profile herunterladen</button> "
        '<span class="hint">Eine JSON-Datei mit allen gespeicherten Profilen. '
        "Ohne Zugangsdaten, ohne Einstellungen, ohne die Rechtedatei "
        "selbst.</span></p>"
        if has_profiles
        else '<p class="hint">Noch nichts zu exportieren.</p>'
    )
    return f"""
<details style="margin-top:.6rem">
  <summary>Profile mitnehmen oder einlesen</summary>
  {export}
  <p><input type="file" id="profilefile" accept="application/json,.json"></p>
  <textarea name="bundle" rows="5"
            placeholder="Inhalt einer Profil-Datei"></textarea>
  <p><button type="submit" name="action" value="profile-import">Profile
     einlesen</button>
  <span class="hint">Legt die Profile an oder überschreibt gleichnamige. An
     den Rechten ändert das nichts.</span></p>
</details>
<script>
(function () {{
  var pick = document.getElementById('profilefile');
  if (!pick) return;
  pick.addEventListener('change', function () {{
    var file = pick.files && pick.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {{
      document.querySelector('textarea[name=bundle]').value = reader.result;
    }};
    reader.readAsText(file);
  }});
}})();
</script>
"""


def message_box(text: str, kind: str = "") -> str:
    """A one-line result of the last action, shown at the top of a page."""
    return note(esc(text), kind)


def raw_message(html_text: str, kind: str = "") -> str:
    """A result that carries its own markup, already escaped by the caller."""
    return note(html_text, kind)


def account_summary(account: Account) -> str:
    """What a successful connection test learned, as a block of markup."""
    bits: list[str] = [f"<strong>{esc(account.label)}</strong>"]
    if account.tax_type:
        bits.append(f"Steuerart: {esc(account.tax_type)}")
    if account.small_business is not None:
        bits.append(
            "Kleinunternehmer" if account.small_business else "kein Kleinunternehmer"
        )
    return " · ".join(bits)
