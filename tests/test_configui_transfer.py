"""The profile export: what it carries, and what it refuses to read."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from benethos_lexware_office_mcp.configui import transfer
from benethos_lexware_office_mcp.configui.profiles import Profile

PROFILES = {
    "Nur Lesen": Profile(
        name="Nur Lesen",
        tools=("get_profile", "search_vouchers"),
        saved="2026-08-22T10:00:00.000000+02:00",
        known=("create_voucher", "get_profile", "search_vouchers"),
    )
}


def build() -> dict:
    return transfer.build(PROFILES, version="9.9.9")


# -- what leaves the machine ------------------------------------------------


def test_only_profiles_travel() -> None:
    """Settings and the policy file were carried once and are not any more.

    `LXO_MCP_TOOL_POLICY` and `LXO_MCP_DOWNLOAD_DIR` are absolute paths
    describing one machine. An import writing the first would have pointed
    the target installation at a policy file that does not exist there, which
    means no tools at all - right after an import that appeared to grant some.
    """
    document = build()

    assert set(document) == {
        "kind",
        "bundleVersion",
        "created",
        "serverVersion",
        "profiles",
    }


def test_no_credential_can_be_in_it_at_all() -> None:
    text = transfer.dumps(build())

    assert "LXO_MCP" not in text
    assert "apiKey" not in text


def test_a_profile_travels_whole() -> None:
    entry = build()["profiles"]["Nur Lesen"]

    assert entry["tools"] == ["get_profile", "search_vouchers"]
    assert entry["known"] == ["create_voucher", "get_profile", "search_vouchers"]
    assert entry["saved"] == "2026-08-22T10:00:00.000000+02:00"


def test_the_file_is_readable_and_stamped() -> None:
    document = build()

    assert document["kind"] == transfer.BUNDLE_KIND
    assert document["serverVersion"] == "9.9.9"
    assert datetime.fromisoformat(document["created"]).tzinfo is not None
    assert transfer.dumps(document).endswith("\n")


# -- what comes back in -----------------------------------------------------


def test_a_bundle_survives_the_round_trip() -> None:
    back = transfer.parse(transfer.dumps(build()))

    assert back == PROFILES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nicht json", "JSON"),
        ("[1, 2]", "Objekt"),
        ('{"kind": "etwas anderes"}', "Profil-Export"),
        (
            json.dumps({"kind": transfer.BUNDLE_KIND, "bundleVersion": 99}),
            "Formatversion",
        ),
        (
            json.dumps(
                {
                    "kind": transfer.BUNDLE_KIND,
                    "bundleVersion": transfer.BUNDLE_VERSION,
                    "profiles": {},
                }
            ),
            "kein einziges lesbares Profil",
        ),
    ],
)
def test_a_file_that_is_not_a_profile_export_is_refused_in_one_sentence(
    text: str, expected: str
) -> None:
    with pytest.raises(transfer.TransferError, match=expected):
        transfer.parse(text)


def test_an_old_configuration_bundle_is_not_mistaken_for_this_one() -> None:
    """The format that carried settings and permissions used another kind."""
    old = json.dumps(
        {
            "kind": "benethos-lexware-office-mcp/config",
            "bundleVersion": 1,
            "settings": {"LXO_MCP_PAGE_SIZE": "50"},
            "tools": {"create_voucher": True},
            "profiles": {"Nur Lesen": {"tools": ["get_profile"]}},
        }
    )

    with pytest.raises(transfer.TransferError, match="Profil-Export"):
        transfer.parse(old)


def test_entries_that_are_not_profiles_are_skipped() -> None:
    text = json.dumps(
        {
            "kind": transfer.BUNDLE_KIND,
            "bundleVersion": transfer.BUNDLE_VERSION,
            "profiles": {
                "gut": {"tools": ["get_profile"]},
                "kaputt": "kein Objekt",
            },
        }
    )

    assert list(transfer.parse(text)) == ["gut"]
