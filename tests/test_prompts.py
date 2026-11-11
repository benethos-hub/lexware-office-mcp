"""The recipes: what a client lists, what it renders, and what the text names.

A recipe names tools, parameters and fields. Nothing at runtime notices when
one of them is renamed, the model would simply be sent to a tool that is not
there, so every name is held here to what the server registers and what the
API was seen to answer with.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from benethos_lexware_office_mcp import prompts
from benethos_lexware_office_mcp.records.types import LinkTarget, SortOrder
from benethos_lexware_office_mcp.server import _registry, build_server
from benethos_lexware_office_mcp.settings import MAX_PAGE_SIZE, Settings

REPO = Path(__file__).resolve().parents[1]
SERVER = build_server(Settings(tool_policy_path=REPO / "no-such-tools.json"))
PROMPTS = asyncio.run(SERVER.list_prompts())
TOOLS = {tool.name: tool for tool in asyncio.run(_registry.list_tools())}
PARAMETERS = {
    name for tool in TOOLS.values() for name in tool.input_schema["properties"]
}


def _fields_the_api_answered_with() -> set[str]:
    """Every field name in the committed shape captures, at any depth."""
    names: set[str] = set()
    for capture in (REPO / "live" / "shapes").glob("*.txt"):
        for line in capture.read_text(encoding="utf-8").splitlines():
            path = re.match(r"([A-Za-z0-9_\[\].]+):", line)
            if path:
                names |= {part.replace("[]", "") for part in path[1].split(".")}
    return names


# The block every list tool answers with beside its rows, and the one key in
# it a recipe reads. See records/formatting.py, `page` and `PAGE_KEYS`.
PAGE_BLOCK = {"page", "last"}
FIELDS = _fields_the_api_answered_with() | PAGE_BLOCK


def _render(name: str, arguments: dict[str, str]) -> str:
    result = asyncio.run(SERVER.get_prompt(name, arguments))
    [message] = result.messages
    assert message.role == "user"
    text: str = message.content.text
    return text


def _placeholder(argument: str) -> str:
    return f"${{arguments.{argument}}}"


def _declared(name: str) -> str:
    """The text with every argument given, as the bundle manifest declares it."""
    prompt = next(p for p in PROMPTS if p.name == name)
    return _render(name, {a.name: _placeholder(a.name) for a in prompt.arguments or []})


# -- what a client lists --------------------------------------------------------


def test_the_client_lists_three_recipes_in_this_order() -> None:
    assert [p.name for p in PROMPTS] == [
        "open_items",
        "missing_receipts",
        "contact_overview",
    ]


def test_they_are_offered_without_a_policy_file() -> None:
    """A recipe reaches no data, the tools it leads to still answer to the file."""
    assert [t.name for t in asyncio.run(SERVER.list_tools())] == ["server_status"]
    assert len(PROMPTS) == 3


def test_each_prompt_sits_in_the_module_of_its_name() -> None:
    """One module per prompt, so a module whose prompt was never registered
    shows here."""
    folder = Path(prompts.__file__).parent
    modules = {p.stem for p in folder.glob("*.py") if not p.stem.startswith("_")}
    assert modules == {p.name for p in PROMPTS}


def test_each_has_a_title_and_a_one_line_description() -> None:
    titles = [p.title for p in PROMPTS]
    assert all(titles) and len(set(titles)) == len(titles)
    for prompt in PROMPTS:
        assert prompt.description and "\n" not in prompt.description


def test_each_argument_is_described() -> None:
    for prompt in PROMPTS:
        assert all(a.description for a in prompt.arguments or []), prompt.name


def test_only_the_contact_overview_requires_its_argument() -> None:
    required = {p.name: [a.required for a in p.arguments or []] for p in PROMPTS}
    assert required == {
        "open_items": [False],
        "missing_receipts": [False],
        "contact_overview": [True],
    }


def test_a_missing_required_argument_is_refused() -> None:
    with pytest.raises(ValueError, match="contact"):
        asyncio.run(SERVER.get_prompt("contact_overview", {}))


# -- what the text names ----------------------------------------------------------


@pytest.mark.parametrize("name", [p.name for p in PROMPTS])
def test_every_name_in_backticks_is_a_tool_or_a_field(name: str) -> None:
    named = set(re.findall(r"`([^`]+)`", _declared(name)))
    assert named - set(TOOLS) - FIELDS == set()


@pytest.mark.parametrize("name", [p.name for p in PROMPTS])
def test_every_parameter_named_is_one_a_tool_takes(name: str) -> None:
    """snake_case outside backticks is a parameter, such as voucher_status."""
    text = re.sub(r"`[^`]+`", "", _declared(name))
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text))
    assert named - PARAMETERS == set()


@pytest.mark.parametrize("name", [p.name for p in PROMPTS])
def test_every_page_size_is_one_the_tools_accept(name: str) -> None:
    sizes = [int(n) for n in re.findall(r"\bsize (\d+)", _declared(name))]
    assert all(1 <= size <= MAX_PAGE_SIZE for size in sizes)


def test_the_sort_order_named_is_one_the_api_takes() -> None:
    assert "sort voucherDate,ASC" in _declared("missing_receipts")
    assert "voucherDate,ASC" in get_args(SortOrder)


@pytest.mark.parametrize("name", ["open_items", "missing_receipts"])
def test_every_link_target_named_is_one_get_deeplink_takes(name: str) -> None:
    targets: set[str] = set()
    for member in get_args(LinkTarget):
        targets |= set(get_args(member)) or {member}
    named = set(re.findall(r"\(([a-z-]+)\)", _declared(name)))
    assert named and named <= targets
    assert "and voucher for the bookkeeping types" in _declared(name)


# -- every recipe minds the same rules ----------------------------------------------


@pytest.mark.parametrize("name", [p.name for p in PROMPTS])
def test_every_recipe_opens_with_the_policy_and_ends_with_the_rules(name: str) -> None:
    text = _declared(name)
    assert "Use only the tools in your list." in text
    assert text.endswith("Give no tax advice.")
    assert "change nothing in the books" in text


# -- the arguments go in as they are ----------------------------------------------


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("open_items", {"contact": "Muster GmbH"}),
        ("open_items", {"contact": ""}),
        ("open_items", {}),
        ("missing_receipts", {"period": "2026-Q3"}),
        ("missing_receipts", {}),
        ("contact_overview", {"contact": "10001"}),
    ],
)
def test_the_text_is_the_declared_one_with_the_arguments_put_in(
    name: str, arguments: dict[str, str]
) -> None:
    """Claude Desktop puts the arguments into the declared text and compares.

    So no recipe may pick a different sentence for an argument left out: the
    text the server renders has to be the declared one, each placeholder
    replaced by what was given, the empty string for what was not.
    """
    prompt = next(p for p in PROMPTS if p.name == name)
    expected = _declared(name)
    for argument in prompt.arguments or []:
        expected = expected.replace(
            _placeholder(argument.name), arguments.get(argument.name, "")
        )

    assert _render(name, arguments) == expected


def test_a_name_given_reaches_no_log_line(caplog: pytest.LogCaptureFixture) -> None:
    """A contact's name is the person's to type and nobody's to log."""
    caplog.set_level(logging.DEBUG)
    _render("contact_overview", {"contact": "Zwetschgenhain 4711"})
    _render("open_items", {"contact": "Zwetschgenhain 4711"})

    assert "Zwetschgenhain" not in caplog.text


def test_a_recipe_asks_lexware_nothing() -> None:
    """Rendering builds text, it reaches no client and no provider."""
    calls: list[Any] = []

    class Refusing:
        def get(self) -> Any:  # pragma: no cover - failing is the point
            calls.append("get")
            raise AssertionError("a prompt reached the API")

    server = build_server(
        Settings(tool_policy_path=REPO / "no-such-tools.json"),
        provider=Refusing(),  # type: ignore[arg-type]
    )
    for prompt in asyncio.run(server.list_prompts()):
        arguments = {a.name: "x" for a in prompt.arguments or []}
        asyncio.run(server.get_prompt(prompt.name, arguments))

    assert calls == []
