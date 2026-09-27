"""The helpers every tool module shares."""

from __future__ import annotations

import pytest

from benethos_lexware_office_mcp.errors import ConflictError
from benethos_lexware_office_mcp.tools._base import require_version


def test_a_matching_version_passes_silently() -> None:
    require_version({"version": 3}, 3, noun="contact", reader="get_contact")


def test_a_stale_version_names_the_record_and_the_tool_that_reads_it() -> None:
    """The advice has to be actionable: which record, and how to re-read it."""
    with pytest.raises(ConflictError) as excinfo:
        require_version({"version": 4}, 3, noun="voucher", reader="get_voucher")

    text = str(excinfo.value)
    assert "This voucher is at version 4" in text
    assert "written against version 3" in text
    assert "get_voucher" in text


def test_a_record_without_a_version_is_a_conflict_too() -> None:
    """None is not the version the caller quoted, so nothing is sent."""
    with pytest.raises(ConflictError):
        require_version({}, 0, noun="article", reader="get_article")
