"""The source checkout's own `config/`, and the guard that limits it there.

A client such as Claude Desktop spawns the server with a working directory of
its own, so a clone had to be startable from anywhere. Resolving the file from
the package location does that, but the same arithmetic lands in
``site-packages`` once the package is installed from a wheel. The
``pyproject.toml`` check is what keeps those two apart, so it is what these
tests are mostly about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_lexware_office_mcp import config as C


def make_checkout(tmp_path: Path, contents: str) -> Path:
    """A directory that looks like a source checkout of this project."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(contents, encoding="utf-8")
    return tmp_path / "config" / ".env"


def pretend_module_lives_at(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `_project_config_dir` believe the package sits under ``root``.

    It derives the root from its own ``__file__``, two levels up, so moving
    that is what exercises the real arithmetic instead of restating it.
    """
    fake = root / "src" / "benethos_lexware_office_mcp" / "config.py"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.touch()
    monkeypatch.setattr(C, "__file__", str(fake))


def test_a_checkout_is_recognised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = make_checkout(tmp_path, "LXO_MCP_PAGE_SIZE=11\n")
    pretend_module_lives_at(tmp_path, monkeypatch)

    assert C._project_config_dir() == expected.parent


def test_an_install_directory_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """site-packages has no pyproject.toml, so nothing is read from it.

    Without the guard this would point into a directory shared with every
    other installed package.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text("LXO_MCP_MODE=full\n", encoding="utf-8")
    pretend_module_lives_at(tmp_path, monkeypatch)

    assert C._project_config_dir() is None


def test_the_real_package_resolves_to_this_repository() -> None:
    """The arithmetic must survive a refactor of the package layout."""
    found = C._project_config_dir()
    assert found is not None
    assert found.name == "config"
    assert (found.parent / "pyproject.toml").is_file()
    assert (found.parent / "src" / "benethos_lexware_office_mcp").is_dir()


def test_the_checkout_is_read_when_the_working_directory_is_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: started from anywhere, the clone still configures itself."""
    env = make_checkout(tmp_path, "LXO_MCP_PAGE_SIZE=11\n")
    monkeypatch.setattr(C, "_project_config_dir", lambda: env.parent)
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(C.os, "environ", {})

    elsewhere = tmp_path / "somewhere_else"
    elsewhere.mkdir()
    assert C._env_lookup(cwd=elsewhere)["LXO_MCP_PAGE_SIZE"] == "11"


def test_nothing_is_read_when_it_is_not_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(C, "_project_config_dir", lambda: None)
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(C.os, "environ", {})

    assert C._env_lookup(cwd=tmp_path) == {}


def test_the_working_directory_outranks_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invocation beats the installation."""
    env = make_checkout(tmp_path, "LXO_MCP_PAGE_SIZE=11\n")
    monkeypatch.setattr(C, "_project_config_dir", lambda: env.parent)
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(C.os, "environ", {})

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("LXO_MCP_PAGE_SIZE=22\n", encoding="utf-8")

    assert C._env_lookup(cwd=elsewhere)["LXO_MCP_PAGE_SIZE"] == "22"


def test_a_real_environment_variable_outranks_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the stdio test relies on to keep a real key out of a subprocess."""
    env = make_checkout(tmp_path, "LXO_MCP_API_KEY=would-be-the-real-key\n")
    monkeypatch.setattr(C, "_project_config_dir", lambda: env.parent)
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(C.os, "environ", {"LXO_MCP_API_KEY": ""})

    assert C._env_lookup(cwd=tmp_path)["LXO_MCP_API_KEY"] == ""
    assert C.load_settings(C._env_lookup(cwd=tmp_path)).api_key is None


# -- one order, every configuration file ----------------------------------


def test_both_files_are_searched_in_the_same_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sequence is the part a person has to keep in their head.

    Two files searched two ways would be two rules to remember, and the one
    remembered wrongly is the one holding the permissions.
    """
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "installed")
    monkeypatch.setattr(C, "_project_config_dir", lambda: tmp_path / "checkout")
    here = tmp_path / "cwd"

    env = [p.parent for p in C.config_candidates(".env", cwd=here)]
    policy = [p.parent for p in C.config_candidates("tools.json", cwd=here)]

    assert env == policy
    assert env == [
        tmp_path / "installed",
        tmp_path / "checkout",
        here / "config",
        here,
    ]


def test_the_checkout_beats_the_installed_policy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Working on the code overrides the installed configuration."""
    installed = tmp_path / "installed"
    checkout = tmp_path / "checkout" / "config"
    for directory in (installed, checkout):
        directory.mkdir(parents=True)
        (directory / "tools.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(C, "config_dir", lambda: installed)
    monkeypatch.setattr(C, "_project_config_dir", lambda: checkout)

    found = C.resolve_config_file("tools.json", cwd=tmp_path / "nowhere")

    assert found == checkout / "tools.json"


def test_a_file_nobody_created_resolves_to_where_it_should_be_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing file still has to name a path, and it must be a writable one."""
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "installed")
    monkeypatch.setattr(C, "_project_config_dir", lambda: None)

    found = C.resolve_config_file("tools.json", cwd=tmp_path / "nowhere")

    assert found == tmp_path / "installed" / "tools.json"
