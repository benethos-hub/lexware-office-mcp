"""What the three pages say, rendered without a server and without a network."""

from __future__ import annotations

import dataclasses
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.configui import pages, probe, templates
from benethos_lexware_office_mcp.configui.state import EDITABLE_KEYS, Installation
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools
from benethos_lexware_office_mcp.settings import Settings, locations


@pytest.fixture(autouse=True)
def only_this_tests_env(
    no_configuration_from_this_machine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing from the developer's machine in the rendered source badges."""
    monkeypatch.setattr(probe, "_last", None)


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_PAGE_SIZE=50\n", encoding="utf-8")
    settings = Settings(
        api_key="secret-value-do-not-print",
        page_size=50,
        tool_policy_path=tmp_path / "tools.json",
    )
    return Installation(settings=settings, env_path=env, cwd=tmp_path)


def text(page: pages.Page) -> str:
    """The page as a browser reads it: a line break in a template is a space."""
    return text_with(page, None)


def text_with(page: pages.Page, message: pages.Message | None) -> str:
    """The page with the message an action left on it."""
    return re.sub(r"\s+", " ", page.html(message=message).decode("utf-8"))


# -- the shell --------------------------------------------------------------


def test_every_page_is_german_and_names_itself(inst: Installation) -> None:
    for render in (
        pages.overview,
        pages.credentials,
        pages.permissions,
        pages.settings,
    ):
        body = text(render(inst))
        assert '<html lang="de">' in body
        assert "Lexware Office MCP</title>" in body
        assert "Übersicht" in body and "Rechte" in body


class Balance(HTMLParser):
    """Enough of a parser to notice a tag nobody closed."""

    VOID = {"br", "hr", "img", "input", "link", "meta"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: list[str] = []
        self.wrong: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in self.VOID:
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.open or self.open[-1] != tag:
            self.wrong.append(
                f"</{tag}> closes <{self.open[-1] if self.open else None}>"
            )
        else:
            self.open.pop()


@pytest.mark.parametrize(
    "render", [pages.overview, pages.credentials, pages.permissions, pages.settings]
)
def test_the_markup_closes_what_it_opens(inst: Installation, render: object) -> None:
    """These pages are built by string concatenation, so this is worth a test.

    Not validation - just the failure that string building actually produces,
    which is a tag left open by an edit three functions away.
    """
    balance = Balance()
    balance.feed(text(render(inst)))  # type: ignore[operator]

    assert balance.wrong == []
    assert balance.open == []


def test_a_page_renders_without_a_server_having_been_built(tmp_path: Path) -> None:
    """The tools do not exist until something builds a server.

    `classify` runs as each tool is registered, so `known_tools()` answers
    with an empty registry in a process that has not done that - and the
    permissions page used to raise `KeyError` there. This has to be a
    subprocess: conftest imports the server for every other test in the file.
    """
    script = f"""
from pathlib import Path
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.configui import pages
from benethos_lexware_office_mcp.configui.state import Installation

tmp = Path(r{str(tmp_path)!r})
(tmp / ".env").write_text("", encoding="utf-8")
inst = Installation(
    settings=Settings(tool_policy_path=tmp / "tools.json"),
    env_path=tmp / ".env",
    cwd=tmp,
)
assert b"get_profile" in pages.permissions(inst).html()
# An empty registry renders as "0 von 0 Tools aktiv" rather than raising.
assert b"von 0 Tools" not in pages.overview(inst).html()
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )

    assert done.returncode == 0, done.stderr


def test_the_page_carries_no_external_reference(inst: Installation) -> None:
    """No CDN, no font host, no analytics. It runs without a network."""
    body = text(pages.overview(inst))

    assert "http://" not in body.replace("http://127.0.0.1", "")
    assert "https://" not in body.replace("https://api.lexware.io", "").replace(
        "https://app.lexware.de", ""
    )


# -- overview ---------------------------------------------------------------


def test_the_overview_never_prints_the_key(inst: Installation) -> None:
    body = text(pages.overview(inst))

    assert "secret-value-do-not-print" not in body
    assert ">hinterlegt</span>" in body


def test_the_overview_says_when_a_server_would_read_a_different_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing a file the server does not read saves and changes nothing.

    One `.env` applies, so a higher one does not shade a value here - it
    replaces the whole file. Without this, the page reports success for work
    that never reaches the server.
    """
    edited = tmp_path / "named.env"
    edited.write_text("LXO_MCP_PAGE_SIZE=50\n", encoding="utf-8")
    higher = tmp_path / ".env"
    higher.write_text("LXO_MCP_PAGE_SIZE=7\n", encoding="utf-8")
    monkeypatch.setattr(
        locations, "config_candidates", lambda name, cwd=None: [tmp_path / name]
    )
    inst = Installation(
        settings=Settings(tool_policy_path=tmp_path / "tools.json"),
        env_path=edited,
        cwd=tmp_path,
    )

    assert inst.outranked_by() == higher
    body = text(pages.overview(inst))
    assert "andere Datei" in body
    assert str(higher) in body


def test_the_overview_stays_quiet_when_it_edits_the_file_that_applies(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ordinary case earns no warning."""
    monkeypatch.setattr(
        locations, "config_candidates", lambda name, cwd=None: [tmp_path / name]
    )

    assert inst.outranked_by() is None
    assert "andere Datei" not in text(pages.overview(inst))


def test_a_missing_policy_file_is_explained_rather_than_shown_as_zero(
    inst: Installation,
) -> None:
    body = text(pages.overview(inst))

    assert "kein einziges Tool" in body
    assert "0 von 25 Tools aktiv" in body


def test_writing_tools_are_named_on_the_overview(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save(
        {"get_profile": True, "create_voucher": True}
    )

    body = text(pages.overview(inst))

    assert "create_voucher" in body
    assert "echte" in body and "Buchhaltungsdaten" in body


def test_a_file_that_enables_nothing_is_not_called_read_only(
    inst: Installation,
) -> None:
    """Nothing enabled is not the same as nothing dangerous enabled.

    The message used to fall through to "alle nur lesend", which reads as
    reassurance about an installation that in fact offers the assistant no
    tool at all.
    """
    ToolPolicy(inst.settings.policy_file()).save(dict.fromkeys(known_tools(), False))

    body = text(pages.overview(inst))

    assert "kein einziges Tool" in body
    assert "nur lesend" not in body


def test_a_read_only_installation_is_not_warned_about(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    assert '<span class="tag ok">nur lesend</span>' in text(pages.overview(inst))


def test_the_context_cost_of_what_is_on_is_shown(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(pages.overview(inst))

    assert "Zeichen, rund" in body and "Token" in body
    # What the permissions page says: the list goes with every request.
    assert "Token je Anfrage" in body


def test_the_files_in_use_are_named_with_their_state(inst: Installation) -> None:
    body = text(pages.overview(inst))

    assert str(inst.env_path) in body
    assert "noch nicht angelegt" in body  # the policy file
    assert "vorhanden" in body  # the .env


def test_the_overview_offers_the_matching_client_arguments(
    inst: Installation,
) -> None:
    """The one direction in which the two processes can be brought together.

    Neither can see how the other was started, and both fix their files at
    start, so all this page can do is say which files it holds.
    """
    body = text(pages.overview(inst))

    assert "--tools-file" in body
    assert "eigenen Prozess" in body
    assert "beim Start fest" in body


def test_a_searched_policy_file_is_not_called_a_default(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody named it, but a resolved path is not a built-in default."""
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.settings.locations.tool_policy_file",
        lambda: inst.policy_path,
    )
    plain = Installation(
        settings=Settings(api_key="x"), env_path=inst.env_path, cwd=inst.cwd
    )

    assert "aus: Suche" in text(pages.overview(plain))


def test_the_flag_outranks_the_variable_on_the_badge_too(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With both set, the path is the flag's, so the source is the flag."""
    monkeypatch.setenv("LXO_MCP_TOOL_POLICY", str(inst.cwd / "from-env.json"))
    named = Installation(
        settings=inst.settings,
        env_path=inst.env_path,
        cwd=inst.cwd,
        tools_file_named=True,
    )

    assert named.source_of("LXO_MCP_TOOL_POLICY") == "Aufruf"
    assert "--tools-file" in named.source_detail("LXO_MCP_TOOL_POLICY")
    assert inst.source_of("LXO_MCP_TOOL_POLICY") == "Umgebung"


def test_the_policy_file_is_fixed_for_the_life_of_the_process(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search can answer differently once a file appears somewhere.

    A process that quietly changed which permissions it edits would be the
    harder thing to reason about, and deleting the pinned file disables
    everything rather than promoting the next candidate.
    """
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.settings.locations.tool_policy_file",
        lambda: tmp_path / "somewhere-else.json",
    )
    plain = Installation(
        settings=Settings(api_key="x"), env_path=inst.env_path, cwd=inst.cwd
    )
    pinned = plain.policy_path

    monkeypatch.setattr(
        "benethos_lexware_office_mcp.settings.locations.tool_policy_file",
        lambda: tmp_path / "higher-precedence.json",
    )
    plain.reload()

    assert plain.policy_path == pinned
    assert plain.policy.path == pinned


def test_a_value_from_the_command_line_is_not_called_a_default(
    inst: Installation,
) -> None:
    """`--tools-file` is neither a file's doing nor a built-in default."""
    assert "aus: Aufruf" in text(pages.overview(inst))


def test_it_stays_the_command_line_after_a_save(inst: Installation) -> None:
    """A save reloads the settings, from files and the environment only."""
    inst.reload()

    assert "aus: Aufruf" in text(pages.overview(inst))


def test_an_environment_variable_outranking_a_file_is_marked(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LXO_MCP_PAGE_SIZE", "9")

    assert "aus: Umgebung" in text(pages.settings(inst))


def _top_right(body: str) -> str:
    return body.split('<div class="right">')[1].split("</header>")[0]


def test_the_first_red_row_is_the_next_step(inst: Installation) -> None:
    """No key comes first: without it nothing else can be tried."""
    inst.settings = dataclasses.replace(inst.settings, api_key="")

    assert "Schlüssel eintragen" in _top_right(text(pages.overview(inst)))

    inst.settings = dataclasses.replace(inst.settings, api_key="k")
    top = _top_right(text(pages.overview(inst)))
    assert '<a class="btn primary" href="/permissions">Rechte festlegen</a>' in top


def test_nothing_red_means_no_next_step(inst: Installation) -> None:
    """An untested connection is no fault: only a button ever tests it."""
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(pages.overview(inst))

    assert "btn primary" not in _top_right(body)
    assert '<span class="tag">nicht getestet</span>' in body


def test_the_stand_names_the_account_once_it_is_known(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        probe, "_last", probe.Account(company="Test Inc.", tax_type="net")
    )

    body = text(pages.overview(inst))

    assert '<span class="tag ok">verbunden</span>' in body
    assert "<strong>Test Inc.</strong> · Steuerart: net" in body


def test_every_file_path_is_folded(inst: Installation) -> None:
    """The name is enough to read, the full path is there for who asks."""
    body = text(pages.overview(inst))

    for path in (inst.env_path, inst.policy_path, inst.profiles.path):
        assert f"<summary>Pfad</summary> <code>{path}</code> </details>" in body
    assert body.count("<code>tools.json</code>") == 1


# -- credentials ------------------------------------------------------------


def test_the_credentials_page_says_where_it_would_write(inst: Installation) -> None:
    body = text(pages.credentials(inst))

    assert str(inst.env_path) in body
    assert "secret-value-do-not-print" not in body


def test_a_shadowed_key_is_flagged_before_anybody_types(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LXO_MCP_API_KEY", "from-the-environment")

    assert "Umgebungsvariablen" in text(pages.credentials(inst))


def test_the_policy_path_cannot_be_edited_here(inst: Installation) -> None:
    """Changing it would swap the subject of the page out from under it."""
    body = text(pages.settings(inst))

    assert 'name="LXO_MCP_PAGE_SIZE"' in body
    assert 'name="LXO_MCP_TOOL_POLICY"' not in body
    assert 'name="LXO_MCP_API_KEY"' not in body  # the key has its own field


# -- settings ---------------------------------------------------------------


def test_every_editable_setting_is_in_exactly_one_card() -> None:
    """A setting added to the server cannot go missing from the page."""
    placed = [key for _, _, keys in pages.SETTINGS_CARDS for key in keys]

    assert sorted(placed) == sorted(EDITABLE_KEYS)
    assert len(placed) == len(set(placed))


def test_the_placeholder_is_the_default_and_the_value_the_file(
    inst: Installation,
) -> None:
    """Empty means the default, so the placeholder shows that, not what applies."""
    body = text(pages.settings(inst))

    assert 'name="LXO_MCP_PAGE_SIZE" type="text" value="50" placeholder="25"' in body
    assert 'name="LXO_MCP_TIMEOUT" type="text" value="" placeholder="30"' in body


def test_the_placeholder_says_what_empty_means_beside_the_other_settings(
    inst: Installation, tmp_path: Path
) -> None:
    """A named download directory is cleaned only when the count says so as
    well, so there an empty count keeps every download, not 100."""
    kept = 'name="LXO_MCP_KEPT_DOWNLOADS" type="text" value="" placeholder="{}"'
    assert kept.format("100") in text(pages.settings(inst))

    named = tmp_path / "downloads"
    inst.env_path.write_text(f"LXO_MCP_DOWNLOAD_DIR={named}\n", encoding="utf-8")
    inst.reload()

    assert kept.format("alle") in text(pages.settings(inst))


def test_a_value_an_environment_variable_holds_is_no_field(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typing over it would change nothing, the variable outranks the file."""
    monkeypatch.setenv("LXO_MCP_TIMEOUT", "45")
    inst.reload()

    body = text(pages.settings(inst))

    assert 'name="LXO_MCP_TIMEOUT"' not in body
    assert '<span class="held">45</span>' in body
    assert "aus: Umgebung" in body


def test_the_log_level_is_a_choice(inst: Installation) -> None:
    body = text(pages.settings(inst))

    assert '<select id="f-LXO_MCP_LOG_LEVEL" name="LXO_MCP_LOG_LEVEL">' in body
    assert '<option value="" selected>Standard (INFO)</option>' in body
    assert '<option value="DEBUG">DEBUG</option>' in body


def test_the_save_button_is_at_the_top_right(inst: Installation) -> None:
    body = text(pages.settings(inst))

    top = body.split('<div class="right">')[1].split("</header>")[0]
    assert 'form="settingsform"' in top
    assert 'id="settingsform"' in body


# -- permissions ------------------------------------------------------------


def test_every_tool_has_a_checkbox(inst: Installation) -> None:
    body = text(pages.permissions(inst))

    for name in known_tools():
        assert f'value="{name}"' in body


def test_a_tool_is_tagged_by_what_it_does(inst: Installation) -> None:
    body = text(pages.permissions(inst))

    assert "lesend</span>" in body
    assert "schreibend · create" in body
    assert "schreibend · delete" in body


def test_destruction_and_permanence_are_different_marks(inst: Installation) -> None:
    """`delete_article` destroys but can be redone. A voucher is the reverse."""
    body = text(pages.permissions(inst))

    assert "nur App" in body
    assert "nur App · Buchhaltung" in body


def test_the_marks_do_not_claim_a_record_can_never_be_deleted(
    inst: Installation,
) -> None:
    """The web app deletes most of it. Only a festgeschrieben document stays.

    An earlier wording said "bleibt dauerhaft" on every one of these, which
    overstated the case the same way the tool descriptions once did - see
    SPECS.md section 5.
    """
    body = text(pages.permissions(inst))

    assert "bleibt dauerhaft" not in body
    assert "Beim Anlegen ist nichts festgeschrieben" in body
    assert "solange nichts" in body
    assert "Storno-Buchung" in body


def test_what_the_marks_mean_is_on_the_page_not_in_a_tooltip(
    inst: Installation,
) -> None:
    body = text(pages.permissions(inst))

    assert "Was die Marken bedeuten" in body
    # The legend explains every mark the rows can carry.
    for mark in ("lesend", "schreibend · create", "schreibend · delete", "nur App"):
        assert mark in body


def test_the_cost_of_each_tool_is_next_to_it(inst: Installation) -> None:
    body = text(pages.permissions(inst))

    assert "Z.</span>" in body
    assert "Token je Anfrage" in body


def test_the_checkboxes_follow_the_file(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(pages.permissions(inst))

    assert 'value="get_profile" id="get_profile" checked' in body
    assert 'value="create_voucher" id="create_voucher">' in body


def test_without_a_file_the_boxes_open_on_read_only(inst: Installation) -> None:
    """A blank form is a poor starting point for a decision.

    A suggestion in a form, not a permission: there is still no file, so
    there are still no tools until somebody saves.
    """
    assert not inst.policy.exists()

    body = text(pages.permissions(inst))

    assert 'value="get_profile" id="get_profile" checked' in body
    assert 'value="create_voucher" id="create_voucher">' in body
    assert "aktiv ist also nichts" in body
    assert "angehakt sind die lesenden" in body


def test_a_loaded_profile_is_not_called_the_suggestion(inst: Installation) -> None:
    """Still no file, so still nothing on, but the ticks are the profile's."""
    body = text(pages.permissions(inst, flags={"create_voucher": True}))

    assert "aktiv ist also nichts" in body
    assert "angehakt sind die lesenden" not in body


def test_ticks_that_do_not_describe_the_file_are_labelled(
    inst: Installation,
) -> None:
    """And once the file exists, the boxes describe it and say nothing."""
    ToolPolicy(inst.settings.policy_file()).save(dict.fromkeys(known_tools(), False))

    body = text(pages.permissions(inst))

    assert 'value="get_profile" id="get_profile">' in body  # off, as the file says
    assert "aktiv ist also nichts" not in body


def test_a_loaded_profile_overrides_the_file_without_writing(
    inst: Installation,
) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(
        pages.permissions(inst, flags={"create_voucher": True, "get_profile": False})
    )

    assert 'value="create_voucher" id="create_voucher" checked' in body
    assert 'value="get_profile" id="get_profile">' in body


def test_the_side_blocks_start_folded_under_the_tools(inst: Installation) -> None:
    """The tool list is the point of the page. The legend, the profiles and
    the file are not, so they come after it, folded."""
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})
    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    body = text(pages.permissions(inst))

    assert body.count("<details") == 3
    assert " open>" not in body
    last_tool = body.rindex('name="tool"')
    for title in (
        "Was die Marken bedeuten",
        "Profile",
        "Rechtedatei: Import und Export",
    ):
        assert body.index(f"<h2>{title}</h2>") > last_tool, title


def test_the_counter_and_the_save_are_at_the_top_right(inst: Installation) -> None:
    """Counted on the server as well, so it is right before any script runs."""
    ToolPolicy(inst.settings.policy_file()).save(
        {"get_profile": True, "search_vouchers": True}
    )

    top = _top_right(text(pages.permissions(inst)))

    assert '<span id="count">2</span> von 25' in top
    assert 'form="permform" name="action" value="save"' in top
    assert re.search(r'<span id="cost">[\d.]+</span>', top)


def test_enter_in_the_profile_name_creates_the_profile(inst: Installation) -> None:
    """A form submits with its first submit button on Enter, and that is
    "Rechte speichern" at the top, which wrote the policy file instead.

    The field names the button Enter stands for, and the script presses it.
    """
    body = text(pages.permissions(inst))

    field = re.search(r'<input id="f-profile_name"[^>]*>', body)
    assert field and 'data-enter="profile-save"' in field.group(0)
    assert 'name="action" value="profile-save"' in body
    script = (templates.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "dataset.enter" in script
    assert "requestSubmit" in script


def test_a_block_unfolds_when_its_own_action_answered(inst: Installation) -> None:
    """A refusal that hides the field it is about helps nobody."""
    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    body = text(pages.permissions(inst, opened="profiles"))

    assert body.count(" open>") == 1
    assert body.index(" open>") < body.index("Rechtedatei: Import und Export")


def test_the_folded_profile_block_still_says_how_many(inst: Installation) -> None:
    assert "— noch keine" in text(pages.permissions(inst))

    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    assert "— 1 gespeichert" in text(pages.permissions(inst))


def test_saved_profiles_are_offered(inst: Installation) -> None:
    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    body = text(pages.permissions(inst))

    assert "Nur Lesen" in body
    assert 'value="profile-delete"' in body
    assert 'value="profile-overwrite"' in body


def test_without_profiles_the_bar_explains_itself(inst: Installation) -> None:
    body = text(pages.permissions(inst))

    assert "Noch keine Profile gespeichert" in body
    assert 'value="load"' not in body


# -- carrying the profiles -------------------------------------------------


def test_the_policy_file_can_be_taken_along(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(pages.permissions(inst))

    assert 'value="policy-export"' in body
    assert 'value="policy-import"' in body
    assert "tools sync" in body


def test_there_is_nothing_to_download_before_a_file_exists(
    inst: Installation,
) -> None:
    body = text(pages.permissions(inst))

    assert 'value="policy-export"' not in body
    assert "keine Rechtedatei zum Herunterladen" in body
    assert 'value="policy-import"' in body  # reading one in still makes sense


def test_nothing_but_the_policy_file_travels(inst: Installation) -> None:
    """Neither the settings nor the profiles are carried any more.

    The settings bundle carried `LXO_MCP_TOOL_POLICY`, an absolute path
    describing one machine, and an import writing it would have pointed the
    target at a policy file that does not exist there.
    """
    for render in (
        pages.overview,
        pages.credentials,
        pages.permissions,
        pages.settings,
    ):
        body = text(render(inst))
        assert "Sichern und Übertragen" not in body
        assert "/transfer" not in body


# -- the account chip -------------------------------------------------------


def test_the_account_appears_on_every_page_once_it_is_known(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which records these permissions apply to has to stay in view."""
    monkeypatch.setattr(probe, "_last", probe.Account(company="Test Inc."))

    for render in (
        pages.overview,
        pages.credentials,
        pages.permissions,
        pages.settings,
    ):
        assert "Konto: Test Inc." in text(render(inst))


def test_an_account_summary_reads_as_a_sentence(inst: Installation) -> None:
    account = probe.Account(company="Test Inc.", tax_type="net", small_business=False)

    body = text_with(
        pages.overview(inst), pages.Message.found("Verbindung steht.", account)
    )

    assert (
        "Verbindung steht. <strong>Test Inc.</strong> · Steuerart: net · "
        "kein Kleinunternehmer</div>"
    ) in body


def test_a_profile_name_is_escaped_not_executed(inst: Installation) -> None:
    inst.profiles.save("<script>böse</script>", (), ())

    body = text(pages.permissions(inst))

    assert "&lt;script&gt;" in body
    assert "<script>böse" not in body


def test_each_box_carries_what_the_tally_needs(inst: Installation) -> None:
    """The policy allows no inline script, so the data is on the boxes."""
    body = text(pages.permissions(inst))

    reading = re.search(
        r'<input type="checkbox" name="tool" ([^>]*value="get_profile"[^>]*)>', body
    )
    removing = re.search(
        r'<input type="checkbox" name="tool" ([^>]*value="delete_article"[^>]*)>', body
    )
    assert reading and removing
    cost = re.search(r'data-cost="(\d+)"', reading.group(1))
    assert cost and int(cost.group(1)) > 0
    assert " data-read" in reading.group(1)
    assert " data-destructive" not in reading.group(1)
    assert " data-destructive" in removing.group(1)
    assert 'data-per-token="3.5"' in body


# -- questions before what cannot be taken back ------------------------------


def test_every_destructive_button_asks_first(inst: Installation) -> None:
    """Deleting or replacing a profile, and a token that locks out clients."""
    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())
    permissions = text(pages.permissions(inst))
    credentials = text(pages.credentials(inst))

    for value in ("profile-delete", "profile-overwrite"):
        button = re.search(rf'<button[^>]*value="{value}"[^>]*>', permissions)
        assert button and "data-confirm=" in button.group(0), value
    generate = re.search(r'<button[^>]*value="generate"[^>]*>', credentials)
    assert generate and "data-confirm=" in generate.group(0)


# -- the credentials page, card by card -----------------------------------


def test_the_token_is_folded_while_the_server_speaks_stdio(
    inst: Installation,
) -> None:
    """It is for the HTTP transport, and there only."""
    folded = text(pages.credentials(inst))
    over_http = dataclasses.replace(inst.settings, transport="streamable-http")
    inst.settings = over_http
    unfolded = text(pages.credentials(inst))

    assert "<h2>HTTP-Token</h2>" in folded
    assert " open>" not in folded
    assert re.search(
        r"<details class=\"card\" open>\s*<summary[^>]*><h2>HTTP-Token", unfolded
    )


def test_a_refused_token_unfolds_its_card(inst: Installation) -> None:
    """Folded, the reason at the top would be about a field nobody sees."""
    body = text(pages.credentials(inst, typed={"LXO_MCP_BEARER_TOKEN": "x y"}))

    assert re.search(
        r"<details class=\"card\" open>\s*<summary[^>]*><h2>HTTP-Token", body
    )
    assert 'value="x y"' in body


def test_a_token_the_environment_holds_is_shown_as_held(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file's token stood in the field under an "aus: Umgebung" badge,
    the one a client would be refused with."""
    inst.env_path.write_text("LXO_MCP_BEARER_TOKEN=from-the-file\n", encoding="utf-8")
    monkeypatch.setenv("LXO_MCP_BEARER_TOKEN", "from-the-environment")
    inst.settings = dataclasses.replace(
        inst.settings, bearer_token="from-the-environment"
    )

    body = text(pages.credentials(inst))

    assert '<span class="held">from-the-environment</span>' in body
    assert "from-the-file" not in body
    assert 'name="bearer"' not in body


def test_the_connection_card_says_what_the_last_test_found(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "noch nicht getestet" in text(pages.credentials(inst))

    monkeypatch.setattr(
        probe, "_last", probe.Account(company="Test Inc.", small_business=True)
    )
    body = text(pages.credentials(inst))

    assert (
        "Zuletzt verbunden mit <strong>Test Inc.</strong> · Kleinunternehmer." in body
    )


def test_the_key_is_saved_from_the_top_right(inst: Installation) -> None:
    body = text(pages.credentials(inst))

    top = body.split('<div class="right">')[1].split("</header>")[0]
    assert 'form="keyform"' in top and "Schlüssel speichern" in top
    assert 'id="keyform"' in body


def test_every_group_offers_the_four_choices_of_the_bar(inst: Installation) -> None:
    """The bar above acts on every tool, the same four act on one group."""
    body = text(pages.permissions(inst))

    for act in ("all-on", "all-off", "all-read", "all-reversible"):
        assert body.count(f'data-act="{act}"') == 1, act
        scoped = act.replace("all-", "grp-")
        assert body.count(f'data-act="{scoped}"') == len(pages.GROUP_LABELS), scoped
