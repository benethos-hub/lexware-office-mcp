"""Output trimming, and the two things that must survive it."""

from __future__ import annotations

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.formatting import compact, profile


def test_nulls_and_empty_containers_are_dropped() -> None:
    assert compact({"a": 1, "b": None, "c": "", "d": [], "e": {}}) == {"a": 1}


def test_zero_and_false_survive() -> None:
    """An open amount of 0 is the answer to 'is it paid', not noise."""
    assert compact({"openAmount": 0, "paid": False, "rate": 0.0}) == {
        "openAmount": 0,
        "paid": False,
        "rate": 0.0,
    }


def test_monetary_values_pass_through_untouched() -> None:
    """Never rounded, never reformatted, never split from the currency."""
    voucher = {"totalGrossAmount": 1234.5600000001, "currency": "EUR"}
    assert compact(voucher) == voucher


def test_nested_structures_are_cleaned_recursively() -> None:
    payload = {
        "address": {"street": "", "city": "Freiburg", "supplement": None},
        "lineItems": [{"name": "Consulting", "note": None}, {}],
    }
    assert compact(payload) == {
        "address": {"city": "Freiburg"},
        "lineItems": [{"name": "Consulting"}],
    }


def test_a_list_that_empties_out_is_dropped_as_well() -> None:
    assert compact({"items": [None, {}, ""]}) == {}


def test_scalars_pass_through() -> None:
    assert compact("EUR") == "EUR"
    assert compact(7) == 7


def test_profile_keeps_every_field_the_api_returned() -> None:
    """The exact field set is unverified, so nothing is dropped by name."""
    payload = {
        "organizationId": "PLACEHOLDER-ORG",
        "companyName": "Example GmbH",
        "taxType": "net",
        "smallBusiness": False,
        "unknownFutureField": "kept",
        "emptyOne": None,
    }
    result = profile(payload)
    assert result["unknownFutureField"] == "kept"
    assert result["smallBusiness"] is False
    assert "emptyOne" not in result


def test_profile_drops_the_creating_user() -> None:
    """userEmail and userName identify a person and are not the tool's job."""
    payload = {
        "organizationId": "PLACEHOLDER-ORG",
        "companyName": "Example GmbH",
        "created": {
            "date": "2026-01-01T00:00:00.000Z",
            "userEmail": "someone@example.invalid",
            "userName": "someone@example.invalid",
        },
    }
    result = profile(payload)
    assert "created" not in result
    assert "example.invalid" not in str(result)


def test_profile_keeps_fields_the_api_adds_later() -> None:
    """A drop-list, not an allow-list, so new fields surface instead of vanishing."""
    result = profile({"companyName": "Example GmbH", "someNewField": "kept"})
    assert result["someNewField"] == "kept"


# -- the shared page envelope ---------------------------------------------


def test_every_list_endpoint_is_shaped_the_same_way() -> None:
    """One page shape across all list tools, so paging is learned once."""
    payload = {
        "content": [{"id": "a"}, {"id": "b"}],
        "first": True,
        "last": False,
        "number": 1,
        "numberOfElements": 2,
        "size": 2,
        "sort": [{"property": "name", "nullHandling": "NATIVE"}],
        "totalElements": 9,
        "totalPages": 5,
    }
    result = formatting.page(payload, lambda item: item, key="articles")

    assert result["articles"] == [{"id": "a"}, {"id": "b"}]
    assert result["page"] == {
        "number": 1,
        "size": 2,
        "totalElements": 9,
        "totalPages": 5,
        "last": False,
    }


def test_the_page_block_keeps_a_false_last() -> None:
    """`last: false` is the signal that another page exists, so it must survive."""
    assert formatting.page_info({"number": 0, "last": False})["last"] is False


def test_a_response_without_content_is_an_empty_list_not_a_crash() -> None:
    assert formatting.page({}, lambda item: item, key="rows")["rows"] == []
