"""One line per tool call, written by the wrapper rather than by the tools."""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.logbook import configure
from benethos_lexware_office_mcp.logbook.output import PACKAGE
from benethos_lexware_office_mcp.policy import ToolPolicy
from helpers import PDF, Scripted, always, recorder, server_with

CONTACT = "0b7a5c9e-3f2d-4e1a-9c8b-7d6e5f4a3b2c"
FILE = "5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1a"
VOUCHER = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
NAME = "Mustermann GmbH"


@pytest.fixture
def lines(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """The tool lines, with the server configured as it configures itself."""
    configure("INFO", io.StringIO())
    caplog.set_level(logging.INFO, logger=PACKAGE)
    return caplog


def _tools(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == f"{PACKAGE}.tools"]


def _only(caplog: pytest.LogCaptureFixture) -> str:
    (record,) = _tools(caplog)
    return record.getMessage()


async def _call(handler: Any, tool: str, arguments: dict[str, Any], **fields: Any):
    server, provider = server_with(handler, **fields)
    try:
        return await server.call_tool(tool, arguments)
    finally:
        await provider.aclose()


# -- reading ---------------------------------------------------------------


async def test_a_search_is_a_count_of_rows_and_never_the_term(
    lines: pytest.LogCaptureFixture,
) -> None:
    page = {"content": [{"id": CONTACT}, {"id": FILE}], "totalElements": 2}

    await _call(always(page), "search_contacts", {"name": NAME})

    message = _only(lines)
    assert message.startswith("search_contacts read 2 rows in 1 API call, ")
    assert "Mustermann" not in lines.text


async def test_a_record_read_is_named_by_its_id(
    lines: pytest.LogCaptureFixture,
) -> None:
    await _call(
        always({"id": CONTACT, "company": {"name": NAME}}),
        "get_contact",
        {"contact_id": CONTACT},
    )

    assert _only(lines).startswith(f"get_contact read {CONTACT} in 1 API call")
    assert "Mustermann" not in lines.text


async def test_a_download_says_its_size_and_never_its_file_name(
    lines: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    handler = recorder(
        headers={
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="Rechnung_Mustermann.pdf"',
        }
    )

    await _call(handler, "download_file", {"file_id": FILE}, download_path=tmp_path)

    message = _only(lines)
    assert message.startswith(f"download_file read {FILE}, {len(PDF)} bytes in 1")
    assert "Mustermann" not in lines.text


# -- writing ---------------------------------------------------------------


async def test_a_creation_is_its_id_and_version_and_nothing_it_was_given(
    lines: pytest.LogCaptureFixture,
) -> None:
    await _call(
        always({"id": CONTACT, "version": 0}, status=200),
        "create_contact",
        {"kind": "company", "name": NAME, "roles": ["customer"]},
    )

    message = _only(lines)
    assert message.startswith(f"create_contact wrote {CONTACT} (version 0) in 1 ")
    assert "Mustermann" not in lines.text


async def test_an_upload_names_the_voucher_it_created(
    lines: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    receipt = tmp_path / "Beleg_Mustermann.pdf"
    receipt.write_bytes(PDF)

    await _call(
        always({"id": FILE, "voucherId": VOUCHER}, status=202),
        "upload_file",
        {"path": str(receipt)},
    )

    assert _only(lines).startswith(f"upload_file wrote {FILE} for voucher {VOUCHER}")
    assert "Mustermann" not in lines.text


async def test_a_finalized_document_says_so(
    lines: pytest.LogCaptureFixture,
) -> None:
    await _call(
        always({"id": FILE, "version": 1}),
        "create_sales_document",
        {
            "document_type": "credit-note",
            "contact_id": CONTACT,
            "voucher_date": "2026-09-30",
            "items": [
                {
                    "name": NAME,
                    "quantity": 1,
                    "unit_name": "Stunde",
                    "unit_price": 10,
                    "tax_rate_percent": 19,
                }
            ],
            "finalize": True,
            "confirm": True,
        },
    )

    assert f"wrote {FILE} (version 1, finalized)" in _only(lines)


async def test_a_delete_is_a_removal(lines: pytest.LogCaptureFixture) -> None:
    await _call(
        Scripted((204, None)), "delete_article", {"article_id": FILE, "confirm": True}
    )

    assert _only(lines).startswith(f"delete_article removed {FILE} in 1 API call")


# -- not doing it ----------------------------------------------------------


async def test_a_refusal_by_the_api_names_its_class_status_and_code(
    lines: pytest.LogCaptureFixture,
) -> None:
    refusal = {"IssueList": [{"source": "version", "i18nKey": "invalid_value"}]}

    with pytest.raises(ToolError):
        await _call(always(refusal, status=406), "get_contact", {"contact_id": CONTACT})

    (record,) = _tools(lines)
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith(
        "get_contact refused: ConflictError 406 version: invalid_value, after 1"
    )


async def test_a_write_that_may_have_happened_failed_with_an_unknown_outcome(
    lines: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(ToolError):
        await _call(
            always({}, status=503),
            "create_contact",
            {"kind": "company", "name": NAME, "roles": ["customer"]},
        )

    assert _only(lines).startswith(
        "create_contact failed: UpstreamError 503, outcome unknown, after 1 API call"
    )
    assert "Mustermann" not in lines.text


async def test_our_own_refusal_names_the_class_and_never_the_message(
    lines: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Its message quotes the path the model named."""
    with pytest.raises(ToolError):
        await _call(
            always({}),
            "upload_file",
            {"path": str(tmp_path / "Mustermann" / "missing.pdf")},
        )

    assert _only(lines).startswith("upload_file refused: ValidationError, after 0")
    assert "Mustermann" not in lines.text


async def test_a_tool_the_policy_withholds_is_a_refusal_too(
    lines: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    policy = tmp_path / "tools.json"
    ToolPolicy(policy).save({"get_profile": True})

    with pytest.raises(ToolError):
        await _call(always({}), "search_contacts", {}, tool_policy_path=policy)

    assert _only(lines).startswith(
        "search_contacts refused: PermissionDeniedError, after 0 API calls"
    )


async def test_arguments_the_schema_refuses_are_named_by_field(
    lines: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(ToolError):
        await _call(always({}), "search_contacts", {"name": NAME, "page": -1})

    assert _only(lines) == "search_contacts refused: invalid page"
    assert "Mustermann" not in lines.text


async def test_a_crash_is_left_to_the_sdk(
    lines: pytest.LogCaptureFixture,
) -> None:
    """It writes the traceback. A line here as well would say it twice."""

    def broken(_request: Any) -> Any:
        raise RuntimeError("not a failure this server knows")

    with pytest.raises(ToolError):
        await _call(broken, "get_profile", {})

    assert _tools(lines) == []


async def test_two_calls_at_once_each_count_their_own(
    lines: pytest.LogCaptureFixture,
) -> None:
    """One count shared between them would say two calls for each."""
    server, provider = server_with(always({"id": CONTACT}))

    await asyncio.gather(
        server.call_tool("get_contact", {"contact_id": CONTACT}),
        server.call_tool("get_contact", {"contact_id": CONTACT}),
    )
    await provider.aclose()

    messages = [record.getMessage() for record in _tools(lines)]
    assert len(messages) == 2
    assert all(" in 1 API call," in message for message in messages)
