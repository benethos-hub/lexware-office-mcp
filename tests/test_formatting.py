"""Output trimming, and the two things that must survive it."""

from __future__ import annotations

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
