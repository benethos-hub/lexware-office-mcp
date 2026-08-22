"""What the three pages say, rendered without a server and without a network."""

from __future__ import annotations

import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import pages, probe
from benethos_lexware_office_mcp.configui.profiles import Profile
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools


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


def text(body: bytes) -> str:
    return body.decode("utf-8")


# -- the shell --------------------------------------------------------------


def test_every_page_is_german_and_names_itself(inst: Installation) -> None:
    for render in (pages.overview, pages.credentials, pages.permissions):
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
    "render", [pages.overview, pages.credentials, pages.permissions]
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
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import pages
from benethos_lexware_office_mcp.configui.state import Installation

tmp = Path(r{str(tmp_path)!r})
(tmp / ".env").write_text("", encoding="utf-8")
inst = Installation(
    settings=Settings(tool_policy_path=tmp / "tools.json"),
    env_path=tmp / ".env",
    cwd=tmp,
)
assert b"get_profile" in pages.permissions(inst)
# An empty registry renders as "0 von 0 Tools aktiv" rather than raising.
assert b"von 0 Tools" not in pages.overview(inst)
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


# -- Übersicht --------------------------------------------------------------


def test_the_overview_never_prints_the_key(inst: Installation) -> None:
    body = text(pages.overview(inst))

    assert "secret-value-do-not-print" not in body
    assert "gesetzt" in body


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

    assert "note good" in text(pages.overview(inst))


def test_the_context_cost_of_what_is_on_is_shown(inst: Installation) -> None:
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})

    body = text(pages.overview(inst))

    assert "Zeichen, rund" in body and "Token" in body


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
        "benethos_lexware_office_mcp.config.tool_policy_file",
        lambda: inst.policy_path,
    )
    plain = Installation(
        settings=Settings(api_key="x"), env_path=inst.env_path, cwd=inst.cwd
    )

    assert "aus: Suche" in text(pages.overview(plain))


def test_the_policy_file_is_fixed_for_the_life_of_the_process(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search can answer differently once a file appears somewhere.

    A process that quietly changed which permissions it edits would be the
    harder thing to reason about, and deleting the pinned file disables
    everything rather than promoting the next candidate.
    """
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.config.tool_policy_file",
        lambda: tmp_path / "somewhere-else.json",
    )
    plain = Installation(
        settings=Settings(api_key="x"), env_path=inst.env_path, cwd=inst.cwd
    )
    pinned = plain.policy_path

    monkeypatch.setattr(
        "benethos_lexware_office_mcp.config.tool_policy_file",
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


def test_an_environment_variable_outranking_a_file_is_marked(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LXO_MCP_PAGE_SIZE", "9")

    assert "aus: Umgebung" in text(pages.overview(inst))


# -- Zugangsdaten -----------------------------------------------------------


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
    body = text(pages.credentials(inst))

    assert 'name="LXO_MCP_PAGE_SIZE"' in body
    assert 'name="LXO_MCP_TOOL_POLICY"' not in body
    assert 'name="LXO_MCP_API_KEY"' not in body  # the key has its own field


# -- Rechte -----------------------------------------------------------------


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


def test_both_side_blocks_start_folded(inst: Installation) -> None:
    """The tool list is the point of the page. These two are not."""
    ToolPolicy(inst.settings.policy_file()).save({"get_profile": True})
    inst.profiles.save("Nur Lesen", ["get_profile"], known_tools())

    body = text(pages.permissions(inst))

    assert body.count("<details") == 2
    assert '<details class="grp" open>' not in body
    assert "Profile <span" in body
    assert "Rechtedatei: Import und Export" in body


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
    for render in (pages.overview, pages.credentials, pages.permissions):
        body = text(render(inst))
        assert "Sichern und Übertragen" not in body
        assert "/transfer" not in body


# -- the account chip -------------------------------------------------------


def test_the_account_appears_on_every_page_once_it_is_known(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which records these permissions apply to has to stay in view."""
    monkeypatch.setattr(probe, "_last", probe.Account(company="Test Inc."))

    for render in (pages.overview, pages.credentials, pages.permissions):
        assert "Konto: Test Inc." in text(render(inst))


def test_an_account_summary_reads_as_a_sentence() -> None:
    account = probe.Account(company="Test Inc.", tax_type="net", small_business=False)

    assert pages.account_summary(account) == (
        "<strong>Test Inc.</strong> · Steuerart: net · kein Kleinunternehmer"
    )


def test_a_profile_name_is_escaped_not_executed(inst: Installation) -> None:
    inst.profiles.replace_all(
        {"<script>böse</script>": Profile(name="<script>böse</script>", tools=())}
    )

    body = text(pages.permissions(inst))

    assert "&lt;script&gt;" in body
    assert "<script>böse" not in body
