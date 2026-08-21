"""Named permission profiles: saved, loaded, and never a second policy."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.configui.profiles import (
    PROFILE_FILE_NAME,
    Profile,
    ProfileError,
    ProfileStore,
    profile_file,
)

KNOWN = ("get_profile", "search_vouchers", "create_voucher")


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / PROFILE_FILE_NAME)


def test_profiles_live_beside_the_policy_they_belong_to(tmp_path: Path) -> None:
    """Naming another policy file has to move the profiles with it."""
    assert profile_file(tmp_path / "sub" / "tools.json") == (
        tmp_path / "sub" / PROFILE_FILE_NAME
    )


def test_no_file_means_no_profiles(store: ProfileStore) -> None:
    assert store.all() == {}
    assert store.get("egal") is None


def test_a_saved_profile_comes_back(store: ProfileStore) -> None:
    store.save("Nur Lesen", ["get_profile", "search_vouchers"], KNOWN)

    profile = store.get("Nur Lesen")
    assert profile is not None
    assert profile.tools == ("get_profile", "search_vouchers")
    assert profile.known == tuple(sorted(KNOWN))
    assert profile.saved


def test_the_timestamp_is_precise_and_unambiguous(store: ProfileStore) -> None:
    """Microseconds and a UTC offset: a bundle travels between machines.

    Bare local times from two time zones would order wrongly, and a date
    alone cannot tell two saves of the same profile apart.
    """
    store.save("Profil", ["get_profile"], KNOWN)
    saved = store.all()["Profil"].saved

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}[+-]\d\d:\d\d", saved)
    assert datetime.fromisoformat(saved).tzinfo is not None


def test_a_name_is_tidied_and_required(store: ProfileStore) -> None:
    store.save("  Zwei   Wörter  ", ["get_profile"], KNOWN)
    assert "Zwei Wörter" in store.all()

    with pytest.raises(ProfileError):
        store.save("   ", ["get_profile"], KNOWN)
    with pytest.raises(ProfileError):
        store.save("x" * 61, ["get_profile"], KNOWN)


def test_saving_the_same_name_replaces_it(store: ProfileStore) -> None:
    store.save("Profil", ["get_profile"], KNOWN)
    store.save("Profil", ["create_voucher"], KNOWN)

    assert store.all()["Profil"].tools == ("create_voucher",)
    assert len(store.all()) == 1


def test_deleting_says_whether_there_was_one(store: ProfileStore) -> None:
    store.save("Profil", ["get_profile"], KNOWN)

    assert store.delete("Profil") is True
    assert store.delete("Profil") is False
    assert store.all() == {}


def test_flags_are_a_complete_map_with_the_rest_off(store: ProfileStore) -> None:
    """A name the profile does not carry is off, like the policy file."""
    store.save("Profil", ["get_profile"], KNOWN)

    assert store.get("Profil").flags(KNOWN) == {  # type: ignore[union-attr]
        "get_profile": True,
        "search_vouchers": False,
        "create_voucher": False,
    }


def test_only_genuinely_newer_tools_are_reported() -> None:
    """Switched off and did-not-exist-yet must not look the same.

    Every tool a profile leaves off would otherwise be announced as new,
    which is noise on every load and hides the one case that matters.
    """
    profile = Profile(name="Profil", tools=("get_profile",), known=tuple(sorted(KNOWN)))

    assert profile.newer_tools(KNOWN) == []
    assert profile.newer_tools([*KNOWN, "brand_new_tool"]) == ["brand_new_tool"]


def test_a_profile_that_never_recorded_the_tools_reports_nothing() -> None:
    """Hand-written, or from an older version. Silence beats a false alarm."""
    profile = Profile(name="Profil", tools=("get_profile",))

    assert profile.newer_tools(KNOWN) == []


def test_a_name_that_is_no_longer_a_tool_is_reported() -> None:
    profile = Profile(name="Profil", tools=("get_profile", "removed_tool"))

    assert profile.unknown(KNOWN) == ["removed_tool"]


def test_merging_says_what_it_overwrote(store: ProfileStore) -> None:
    store.save("Alt", ["get_profile"], KNOWN)

    overwritten = store.merge(
        {
            "Alt": Profile(name="Alt", tools=("create_voucher",)),
            "Neu": Profile(name="Neu", tools=("get_profile",)),
        }
    )

    assert overwritten == ["Alt"]
    assert set(store.all()) == {"Alt", "Neu"}
    assert store.all()["Alt"].tools == ("create_voucher",)


def test_replace_all_drops_what_was_there(store: ProfileStore) -> None:
    store.save("Alt", ["get_profile"], KNOWN)

    store.replace_all({"Neu": Profile(name="Neu", tools=())})

    assert list(store.all()) == ["Neu"]


def test_an_unreadable_file_yields_nothing_rather_than_raising(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken convenience file must not take the interface down."""
    path = tmp_path / PROFILE_FILE_NAME
    path.write_text("{not json", encoding="utf-8")

    assert ProfileStore(path).all() == {}
    assert "Unreadable profiles" in caplog.text


def test_entries_that_are_not_profiles_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / PROFILE_FILE_NAME
    path.write_text(
        '{"version": 1, "profiles": {"gut": {"tools": ["get_profile"]}, '
        '"kaputt": "kein Objekt", "leer": {}}}',
        encoding="utf-8",
    )

    assert list(ProfileStore(path).all()) == ["gut"]


def test_the_stored_file_is_readable_by_a_person(store: ProfileStore) -> None:
    store.save("Für Steuerberater", ["get_profile"], KNOWN)

    text = store.path.read_text(encoding="utf-8")
    assert "Für Steuerberater" in text  # not escaped into ü
    assert text.endswith("\n")
