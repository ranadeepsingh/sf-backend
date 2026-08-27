import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Address

BASE = "/api/v1/contacts"

HOME = {
    "type": "Home",
    "address": "1 Market St",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94105",
    "country": "USA",
}
WORK = {
    "type": "Work",
    "address": "2 King St",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94107",
    "country": "USA",
}


def test_two_addresses_round_trip_through_create_read_and_list(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME, WORK]})
    assert created.status_code == 201, created.text

    addresses = created.json()["addresses"]
    assert [item["type"] for item in addresses] == ["Home", "Work"]
    assert all(item["id"] > 0 for item in addresses)

    contact_id = created.json()["id"]
    assert client.get(f"{BASE}/{contact_id}").json()["addresses"] == addresses
    assert client.get(BASE).json()["items"][0]["addresses"] == addresses


def test_address_rows_belong_to_the_created_contact(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]

    with SessionLocal() as db:
        rows = db.execute(select(Address).order_by(Address.id)).scalars().all()

    assert [row.contact_id for row in rows] == [contact_id, contact_id]


def test_scalar_patch_preserves_addresses(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    updated = client.patch(
        f"{BASE}/{created['id']}", json={"phone": "+1-000-000-0000"}
    )

    assert updated.status_code == 200
    assert updated.json()["addresses"] == created["addresses"]


def test_patch_replaces_addresses_atomically(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    updated = client.patch(f"{BASE}/{created['id']}", json={"addresses": [WORK]})

    assert updated.status_code == 200
    assert updated.json()["addresses"][0]["type"] == "Work"
    assert updated.json()["addresses"][0]["id"] != created["addresses"][0]["id"]
    assert len(updated.json()["addresses"]) == 1


def test_patch_null_clears_addresses(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    updated = client.patch(f"{BASE}/{created['id']}", json={"addresses": None})

    assert updated.status_code == 200
    assert updated.json()["addresses"] == []


def test_put_omission_clears_addresses(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    updated = client.put(
        f"{BASE}/{created['id']}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )

    assert updated.status_code == 200
    assert updated.json()["addresses"] == []


def test_put_replaces_addresses(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    updated = client.put(
        f"{BASE}/{created['id']}", json={**payload, "addresses": [WORK]}
    )

    assert updated.status_code == 200
    assert [item["type"] for item in updated.json()["addresses"]] == ["Work"]


def test_deleting_contact_cascades_to_addresses(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Address)) == 0


@pytest.mark.parametrize("address_type", ["home", "HOME", "Business", ""])
def test_unsupported_address_type_is_rejected(client, payload, address_type):
    response = client.post(
        BASE,
        json={**payload, "addresses": [{**HOME, "type": address_type}]},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "address",
    [
        {"type": "Other"},
        {
            "type": "Other",
            "address": " ",
            "city": "\t",
            "state": "",
            "postal_code": None,
            "country": None,
        },
    ],
)
def test_address_without_content_is_rejected(client, payload, address):
    response = client.post(BASE, json={**payload, "addresses": [address]})
    assert response.status_code == 422


def test_invalid_patch_does_not_replace_existing_addresses(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME]}).json()

    response = client.patch(
        f"{BASE}/{created['id']}", json={"addresses": [{"type": "Work"}]}
    )

    assert response.status_code == 422
    assert client.get(f"{BASE}/{created['id']}").json()["addresses"] == created["addresses"]


def test_addresses_are_documented_in_openapi(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert set(schemas["AddressInput"]["required"]) == {"type"}
    assert set(schemas["AddressRead"]["required"]) == {"type", "id"}
    assert schemas["AddressInput"]["properties"]["type"]["enum"] == ["Home", "Work", "Other"]
    for name in ("ContactCreate", "ContactReplace", "ContactUpdate", "ContactRead"):
        assert "addresses" in schemas[name]["properties"]
        assert "address" not in schemas[name]["properties"]
        assert "city" not in schemas[name]["properties"]
