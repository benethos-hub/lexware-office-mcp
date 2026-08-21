"""The export bundle: what it carries, what it refuses, what it would change."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from benethos_lexware_office_mcp.configui import transfer
from benethos_lexware_office_mcp.configui.profiles import Profile

SETTINGS = {
    "LXO_MCP_API_KEY": "a-real-looking-secret",
    "LXO_MCP_PAGE_SIZE": "50",
    "SOMETHING_ELSE": "not ours",
}
TOOLS = {"get_profile": True, "create_voucher": False}
PROFILES = {"Nur Lesen": Profile(name="Nur Lesen", tools=("get_profile",))}


def build() -> dict:
    return transfer.build(SETTINGS, TOOLS, PROFILES, version="9.9.9")


# -- what leaves the machine ------------------------------------------------


def test_the_api_key_never_travels() -> None:
    """The one rule this format exists under, tested as text as well.

    Checking the parsed document alone would miss a copy of the key sitting
    somewhere else in the file, and the file is the thing that gets sent.
    """
    document = build()

    assert document["apiKey"] is None
    assert "LXO_MCP_API_KEY" not in document["settings"]
    assert "a-real-looking-secret" not in transfer.dumps(document)


def test_the_absence_is_stated_rather_than_left_to_be_noticed() -> None:
    assert "Schlüssel" in build()["apiKeyNote"]


def test_only_this_projects_settings_are_carried() -> None:
    assert set(build()["settings"]) == {"LXO_MCP_PAGE_SIZE"}


def test_every_flag_travels_including_the_ones_that_are_off() -> None:
    """A bundle that only listed what is on could not switch anything off."""
    assert build()["tools"] == {"create_voucher": False, "get_profile": True}


def test_the_file_is_readable_and_stamped() -> None:
    document = build()

    assert document["kind"] == transfer.BUNDLE_KIND
    assert document["serverVersion"] == "9.9.9"
    assert datetime.fromisoformat(document["created"]).tzinfo is not None
    assert transfer.dumps(document).endswith("\n")


# -- what comes back in -----------------------------------------------------


def test_a_bundle_survives_the_round_trip() -> None:
    bundle = transfer.parse(transfer.dumps(build()))

    assert bundle.settings == {"LXO_MCP_PAGE_SIZE": "50"}
    assert bundle.tools == TOOLS
    assert bundle.profiles["Nur Lesen"].tools == ("get_profile",)
    assert bundle.version == "9.9.9"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nicht json", "JSON"),
        ("[1, 2]", "Objekt"),
        ('{"kind": "etwas anderes"}', "diesem Server"),
        (
            json.dumps({"kind": transfer.BUNDLE_KIND, "bundleVersion": 99}),
            "Formatversion",
        ),
    ],
)
def test_a_file_that_is_not_a_bundle_is_refused_in_one_sentence(
    text: str, expected: str
) -> None:
    with pytest.raises(transfer.TransferError, match=expected):
        transfer.parse(text)


def test_a_key_smuggled_into_the_settings_is_dropped_on_the_way_in() -> None:
    """Someone may edit the file. It still must not deliver a key."""
    document = build()
    document["settings"]["LXO_MCP_API_KEY"] = "sneaked in"

    assert "LXO_MCP_API_KEY" not in transfer.parse(json.dumps(document)).settings


# -- what it would change ---------------------------------------------------


def compare(bundle: transfer.Bundle, **kwargs) -> transfer.Changes:
    return transfer.compare(
        bundle,
        current_settings=kwargs.get("settings", {}),
        current_tools=kwargs.get("tools", {}),
        current_profiles=kwargs.get("profiles", {}),
    )


def test_nothing_to_do_is_said_rather_than_shown_as_an_empty_list() -> None:
    bundle = transfer.parse(transfer.dumps(build()))

    changes = compare(
        bundle,
        settings={"LXO_MCP_PAGE_SIZE": "50"},
        tools=TOOLS,
        profiles=bundle.profiles,
    )

    assert changes.empty


def test_switching_a_tool_on_is_reported_separately_from_switching_one_off() -> None:
    bundle = transfer.Bundle(tools={"get_profile": True, "create_voucher": False})

    changes = compare(bundle, tools={"get_profile": False, "create_voucher": True})

    assert changes.turn_on == ["get_profile"]
    assert changes.turn_off == ["create_voucher"]


def test_a_tool_this_installation_does_not_have_is_reported_and_ignored() -> None:
    bundle = transfer.Bundle(tools={"from_the_future": True})

    changes = compare(bundle, tools={"get_profile": False})

    assert changes.unknown_tools == ["from_the_future"]
    assert changes.turn_on == []


def test_a_tool_the_bundle_is_silent_about_keeps_its_setting() -> None:
    """An import completes a policy file. It does not replace one."""
    bundle = transfer.Bundle(tools={"get_profile": True})

    changes = compare(bundle, tools={"get_profile": False, "create_voucher": True})

    assert changes.unmentioned_tools == ["create_voucher"]
    assert changes.turn_off == []


def test_a_changed_setting_shows_both_values() -> None:
    bundle = transfer.Bundle(settings={"LXO_MCP_PAGE_SIZE": "50"})

    changes = compare(bundle, settings={"LXO_MCP_PAGE_SIZE": "25"})

    assert changes.settings == [("LXO_MCP_PAGE_SIZE", "25", "50")]


def test_profiles_are_split_into_new_and_overwritten() -> None:
    bundle = transfer.Bundle(
        profiles={
            "Alt": Profile(name="Alt", tools=("create_voucher",)),
            "Neu": Profile(name="Neu", tools=()),
        }
    )

    changes = compare(
        bundle, profiles={"Alt": Profile(name="Alt", tools=("get_profile",))}
    )

    assert changes.new_profiles == ["Neu"]
    assert changes.overwritten_profiles == ["Alt"]


def test_a_profile_that_already_says_this_is_not_called_overwritten() -> None:
    """Importing the same file twice must not claim damage the second time."""
    same = Profile(name="Alt", tools=("get_profile",))
    bundle = transfer.Bundle(profiles={"Alt": same})

    assert compare(bundle, profiles={"Alt": same}).overwritten_profiles == []
