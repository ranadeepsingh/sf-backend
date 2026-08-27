import pytest

BASE = "/api/v1/contacts"


def test_gender_defaults_to_unknown(client, payload):
    body = client.post(BASE, json=payload).json()

    assert body["gender"] == "unknown"
    assert client.get(f"{BASE}/{body['id']}").json()["gender"] == "unknown"


@pytest.mark.parametrize("gender", ["male", "female", "unknown"])
def test_supported_gender_round_trips(client, payload, gender):
    response = client.post(BASE, json={**payload, "gender": gender})

    assert response.status_code == 201, response.text
    assert response.json()["gender"] == gender


@pytest.mark.parametrize("gender", ["Male", "FEMALE", "other", "", None])
def test_unsupported_gender_is_rejected(client, payload, gender):
    response = client.post(BASE, json={**payload, "gender": gender})

    assert response.status_code == 422


def test_patch_preserves_or_updates_gender(client, payload):
    contact_id = client.post(BASE, json={**payload, "gender": "female"}).json()["id"]

    preserved = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    updated = client.patch(f"{BASE}/{contact_id}", json={"gender": "male"})

    assert preserved.json()["gender"] == "female"
    assert updated.json()["gender"] == "male"


def test_put_omission_resets_gender_to_unknown(client, payload):
    contact_id = client.post(BASE, json={**payload, "gender": "female"}).json()["id"]

    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["gender"] == "unknown"


def test_gender_is_documented_in_openapi(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    for name in ("ContactCreate", "ContactReplace", "ContactUpdate", "ContactRead"):
        assert "gender" in schemas[name]["properties"]
    assert schemas["Gender"]["enum"] == ["male", "female", "unknown"]
