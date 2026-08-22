"""Reading and writing a policy file, the shape it already has on disk."""

from __future__ import annotations

import json

import pytest

from benethos_lexware_office_mcp.configui import transfer
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset

FLAGS = {"get_profile": True, "create_voucher": False}


# -- what leaves the machine ------------------------------------------------


def test_the_download_is_the_file_itself(tmp_path) -> None:
    """No wrapper: a downloaded file has to be usable as `--tools-file`.

    Compared against what `ToolPolicy` writes rather than against a literal,
    so the two cannot drift apart.
    """
    policy = ToolPolicy(tmp_path / "tools.json")
    policy.save(preset("read-only"))

    assert transfer.dumps(policy.as_map()) == policy.path.read_text(encoding="utf-8")


def test_flags_that_are_off_are_written_too() -> None:
    """A file listing only what is on would read as a file listing nothing."""
    text = transfer.dumps(FLAGS)

    assert json.loads(text) == FLAGS
    assert text.endswith("\n")


def test_names_are_sorted_so_two_downloads_can_be_compared() -> None:
    text = transfer.dumps({"zzz": True, "aaa": False})

    assert list(json.loads(text)) == ["aaa", "zzz"]


def test_nothing_but_flags_is_in_it() -> None:
    document = json.loads(transfer.dumps(FLAGS))

    assert set(document) == set(FLAGS)


# -- what comes back in -----------------------------------------------------


def test_a_file_survives_the_round_trip() -> None:
    assert transfer.parse(transfer.dumps(FLAGS)) == FLAGS


def test_a_file_written_by_the_command_line_reads_here() -> None:
    assert transfer.parse(transfer.dumps(preset("read-only"))) == preset("read-only")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nicht json", "JSON"),
        ("[1, 2]", "JSON-Objekt"),
        ('"nur ein string"', "JSON-Objekt"),
        ("{}", "kein einziges Tool"),
    ],
)
def test_a_file_that_is_not_a_policy_is_refused_in_one_sentence(
    text: str, expected: str
) -> None:
    with pytest.raises(transfer.TransferError, match=expected):
        transfer.parse(text)


def test_a_value_that_is_not_a_boolean_is_read_as_one() -> None:
    """The server does the same, so a stricter reader would refuse files that
    work: `ToolPolicy` puts `bool()` around whatever it finds."""
    assert transfer.parse('{"get_profile": 1, "create_voucher": null}') == {
        "get_profile": True,
        "create_voucher": False,
    }


def test_a_profile_export_is_not_mistaken_for_a_policy_file() -> None:
    """The format that carried profiles was wrapped, so it has no flags."""
    old = json.dumps(
        {
            "kind": "benethos-lexware-office-mcp/profiles",
            "bundleVersion": 1,
            "profiles": {"Nur Lesen": {"tools": ["get_profile"]}},
        }
    )

    flags = transfer.parse(old)

    assert not any(name in known_tools() for name in flags)
