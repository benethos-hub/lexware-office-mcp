"""Tool arguments to request bodies.

The merging half of this is the part that matters. ``PUT /v1/contacts/{id}``
replaces the record, so a body that is merely incomplete is not a partial
update, it is data loss. Every test here that carries a ``base`` is really
asking the same question: what did the caller *not* mention, and is it still
there afterwards.
"""

from __future__ import annotations

from typing import Any

from benethos_lexware_office_mcp.payloads import Address, contact_body

BERLIN = Address(street="Musterweg 1", zip="10115", city="Berlin", country_code="DE")

# A contact as the live API returned it on 2026-08-20, read-only fields and
# all. Those fields are what an update sends back untouched.
CURRENT: dict[str, Any] = {
    "id": "PLACEHOLDER-CONTACT-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "version": 2,
    "roles": {"customer": {"number": 10003}, "vendor": {"number": 70002}},
    "company": {"name": "Beispiel GmbH", "vatRegistrationId": "DE999999999"},
    "addresses": {
        "billing": [
            {
                "street": "Rechnungsweg 3",
                "zip": "10119",
                "city": "Berlin",
                "countryCode": "DE",
            }
        ],
        "shipping": [
            {
                "street": "Lieferweg 4",
                "zip": "10119",
                "city": "Berlin",
                "countryCode": "DE",
            }
        ],
    },
    "emailAddresses": {"business": ["buchhaltung@example.invalid"]},
    "phoneNumbers": {"business": ["+49 30 5555555"]},
    "note": "angelegt ueber create_contact",
    "archived": False,
}


# -- creating -------------------------------------------------------------


def test_a_new_contact_starts_at_version_zero() -> None:
    """What the API expects for a record that does not exist yet."""
    body = contact_body(kind="company", name="Neu GmbH", roles=["customer"])
    assert body["version"] == 0


def test_a_company_is_named_in_the_company_block() -> None:
    body = contact_body(kind="company", name="Neu GmbH", roles=["customer"])
    assert body["company"] == {"name": "Neu GmbH"}
    assert "person" not in body


def test_a_person_is_named_in_the_person_block() -> None:
    """The API refuses a record carrying both blocks, so only one is written."""
    body = contact_body(
        kind="person",
        name="Musterperson",
        first_name="Testa",
        salutation="Frau",
        roles=["customer"],
    )
    assert body["person"] == {
        "lastName": "Musterperson",
        "firstName": "Testa",
        "salutation": "Frau",
    }
    assert "company" not in body


def test_roles_become_the_blocks_the_api_wants() -> None:
    body = contact_body(kind="company", name="Neu GmbH", roles=["customer", "vendor"])
    assert body["roles"] == {"customer": {}, "vendor": {}}


def test_a_company_files_its_address_under_business() -> None:
    body = contact_body(
        kind="company", name="Neu GmbH", roles=["customer"], email="a@example.invalid"
    )
    assert body["emailAddresses"] == {"business": ["a@example.invalid"]}


def test_a_person_files_theirs_under_private() -> None:
    body = contact_body(
        kind="person", name="Muster", roles=["customer"], phone="+49 170 1"
    )
    assert body["phoneNumbers"] == {"private": ["+49 170 1"]}


def test_an_address_is_translated_into_the_api_s_field_names() -> None:
    body = contact_body(
        kind="company", name="Neu GmbH", roles=["customer"], billing_address=BERLIN
    )
    assert body["addresses"]["billing"] == [
        {"street": "Musterweg 1", "zip": "10115", "city": "Berlin", "countryCode": "DE"}
    ]


def test_an_unfilled_address_line_is_left_out_rather_than_sent_as_null() -> None:
    body = contact_body(
        kind="company", name="Neu GmbH", roles=["customer"], billing_address=BERLIN
    )
    assert "supplement" not in body["addresses"]["billing"][0]


def test_company_only_fields_are_not_written_onto_a_person() -> None:
    body = contact_body(
        kind="person",
        name="Muster",
        roles=["customer"],
        vat_registration_id="DE123456789",
    )
    assert "company" not in body


# -- updating -------------------------------------------------------------


def test_an_update_carries_the_version_it_read() -> None:
    """Which is what makes a concurrent change fail instead of vanish."""
    body = contact_body(base=CURRENT, note="neu")
    assert body["version"] == 2


def test_changing_one_field_keeps_everything_else() -> None:
    """The whole reason this function takes a base at all."""
    body = contact_body(base=CURRENT, email="neu@example.invalid")

    assert body["emailAddresses"] == {"business": ["neu@example.invalid"]}
    assert body["addresses"] == CURRENT["addresses"]
    assert body["phoneNumbers"] == CURRENT["phoneNumbers"]
    assert body["note"] == CURRENT["note"]
    assert body["company"] == CURRENT["company"]


def test_the_base_is_not_modified() -> None:
    """A builder that edits its input corrupts the record it was handed."""
    before = {"emails": CURRENT["emailAddresses"], "company": dict(CURRENT["company"])}
    contact_body(base=CURRENT, email="neu@example.invalid", name="Anders GmbH")

    assert CURRENT["emailAddresses"] == before["emails"]
    assert CURRENT["company"] == before["company"]


def test_renaming_a_company_keeps_its_tax_details() -> None:
    body = contact_body(base=CURRENT, name="Umbenannt GmbH")
    assert body["company"] == {
        "name": "Umbenannt GmbH",
        "vatRegistrationId": "DE999999999",
    }


def test_the_kind_does_not_have_to_be_restated_on_an_update() -> None:
    """A contact cannot turn from a company into a person, so it is read off."""
    body = contact_body(base=CURRENT, email="neu@example.invalid")
    assert body["emailAddresses"] == {"business": ["neu@example.invalid"]}


def test_a_person_is_recognised_from_the_record_being_updated() -> None:
    person = {"version": 1, "roles": {"customer": {}}, "person": {"lastName": "Muster"}}
    body = contact_body(base=person, email="neu@example.invalid")
    assert body["emailAddresses"] == {"private": ["neu@example.invalid"]}


def test_adding_a_role_keeps_the_number_the_other_one_already_has() -> None:
    body = contact_body(base=CURRENT, roles=["customer", "vendor"])
    assert body["roles"]["customer"] == {"number": 10003}
    assert body["roles"]["vendor"] == {"number": 70002}


def test_leaving_a_role_out_removes_it() -> None:
    body = contact_body(base=CURRENT, roles=["customer"])
    assert "vendor" not in body["roles"]


def test_roles_are_untouched_when_they_are_not_mentioned() -> None:
    body = contact_body(base=CURRENT, note="neu")
    assert body["roles"] == CURRENT["roles"]


def test_replacing_the_billing_address_leaves_the_shipping_one_alone() -> None:
    body = contact_body(base=CURRENT, billing_address=BERLIN)
    assert body["addresses"]["billing"][0]["street"] == "Musterweg 1"
    assert body["addresses"]["shipping"] == CURRENT["addresses"]["shipping"]


def test_read_only_fields_are_carried_back_unchanged() -> None:
    """Verified live: the API accepts and ignores them, so stripping them is
    work with no benefit and a risk of dropping something that matters."""
    body = contact_body(base=CURRENT, note="neu")
    assert body["organizationId"] == "PLACEHOLDER-ORG-ID"
    assert body["archived"] is False


def test_a_note_can_be_cleared() -> None:
    """An empty string is a change. Only None means "not mentioned"."""
    body = contact_body(base=CURRENT, note="")
    assert body["note"] == ""


def test_a_company_carries_its_tax_details() -> None:
    body = contact_body(
        kind="company",
        name="Neu GmbH",
        roles=["customer"],
        vat_registration_id="DE123456789",
        tax_number="12345/67890",
    )
    assert body["company"] == {
        "name": "Neu GmbH",
        "vatRegistrationId": "DE123456789",
        "taxNumber": "12345/67890",
    }


def test_a_shipping_address_can_stand_on_its_own() -> None:
    body = contact_body(
        kind="company", name="Neu GmbH", roles=["customer"], shipping_address=BERLIN
    )
    assert body["addresses"]["shipping"][0]["city"] == "Berlin"
    assert "billing" not in body["addresses"]


def test_a_contact_with_no_role_named_becomes_a_customer() -> None:
    """The API refuses a contact with neither role, so one has to be chosen."""
    body = contact_body(kind="company", name="Neu GmbH")
    assert body["roles"] == {"customer": {}}
