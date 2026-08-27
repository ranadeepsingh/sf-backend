"""Coverage for the optional `photo` base64 data-URL field."""

import base64

import pytest

from app.photo import MAX_PHOTO_BASE64_CHARS, MAX_PHOTO_BYTES, validate_photo_data_url
from app.seed import SAMPLE_CONTACTS

BASE = "/api/v1/contacts"

# Leading bytes that identify each supported format, padded into a small body so
# the samples are large enough to be decoded but stay readable in test output.
IMAGE_MAGIC = {
    "image/jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 12,
    "image/png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 12,
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 12,
}


def data_url(mime: str = "image/png") -> str:
    """Build a canonical base64 data URL with the selected image signature."""
    return f"data:{mime};base64,{base64.b64encode(IMAGE_MAGIC[mime]).decode()}"


@pytest.fixture
def photo() -> str:
    return data_url("image/png")


def test_photo_defaults_to_null(client, payload):
    body = client.post(BASE, json=payload).json()
    assert body["photo"] is None


def test_seed_contacts_default_to_null_photo():
    assert SAMPLE_CONTACTS
    assert all(contact.photo is None for contact in SAMPLE_CONTACTS)


@pytest.mark.parametrize("mime", sorted(IMAGE_MAGIC))
def test_create_accepts_every_supported_format(client, payload, mime):
    photo = data_url(mime)
    response = client.post(BASE, json={**payload, "photo": photo})
    assert response.status_code == 201, response.text
    assert response.json()["photo"] == photo


def test_photo_round_trips_through_get_and_list(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]

    assert client.get(f"{BASE}/{contact_id}").json()["photo"] == photo

    items = client.get(BASE).json()["items"]
    assert [item["photo"] for item in items] == [photo]


def test_create_accepts_explicit_null(client, payload):
    response = client.post(BASE, json={**payload, "photo": None})
    assert response.status_code == 201
    assert response.json()["photo"] is None


@pytest.mark.parametrize(
    "photo",
    [
        "not-a-data-url",
        "data:image/png,iVBORw0KGgo=",  # missing ;base64
        "data:image/png;base64",  # missing comma and payload
        "image/png;base64,iVBORw0KGgo=",  # missing data: scheme
        "",
    ],
    ids=["plain-text", "no-base64-marker", "no-payload-separator", "no-scheme", "empty-string"],
)
def test_malformed_data_url_is_rejected(client, payload, photo):
    response = client.post(BASE, json={**payload, "photo": photo})
    assert response.status_code == 422


def test_empty_payload_is_rejected(client, payload):
    response = client.post(BASE, json={**payload, "photo": "data:image/png;base64,"})
    assert response.status_code == 422
    assert "empty" in response.text


@pytest.mark.parametrize(
    "photo",
    [
        "data:image/png;base64,!!!!not base64!!!!",
        "data:image/png;base64,iVBORw0KGgo",  # missing padding
        "data:image/png;base64,iVBORw0KGgo==",  # wrong padding length
    ],
    ids=["bad-alphabet", "missing-padding", "wrong-padding"],
)
def test_malformed_base64_is_rejected(client, payload, photo):
    response = client.post(BASE, json={**payload, "photo": photo})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload_suffix",
    ["\n", "\r\n", " ", "\t", "-_"],
    ids=["newline", "crlf", "space", "tab", "url-safe-alphabet"],
)
def test_whitespace_and_nonstandard_base64_are_rejected(client, payload, payload_suffix):
    encoded = base64.b64encode(IMAGE_MAGIC["image/png"]).decode()
    response = client.post(
        BASE,
        json={**payload, "photo": f"data:image/png;base64,{encoded}{payload_suffix}"},
    )
    assert response.status_code == 422
    assert "base64" in response.text


def test_non_canonical_base64_is_rejected(client, payload):
    # "iVBORw0KGgp=" decodes to the same bytes as the canonical "iVBORw0KGgo=",
    # because the final character carries unused bits that are not zero.
    canonical = base64.b64encode(base64.b64decode("iVBORw0KGgo=")).decode()
    assert canonical != "iVBORw0KGgp="

    response = client.post(BASE, json={**payload, "photo": "data:image/png;base64,iVBORw0KGgp="})
    assert response.status_code == 422
    assert "canonical" in response.text


@pytest.mark.parametrize(
    "mime",
    ["image/gif", "image/svg+xml", "image/bmp", "text/plain", "application/pdf"],
)
def test_unsupported_mime_type_is_rejected(client, payload, mime):
    encoded = base64.b64encode(IMAGE_MAGIC["image/png"]).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:{mime};base64,{encoded}"})
    assert response.status_code == 422
    assert "unsupported" in response.text.lower()


def test_mime_type_must_use_canonical_lowercase(client, payload):
    encoded = base64.b64encode(IMAGE_MAGIC["image/png"]).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/PNG;base64,{encoded}"})
    assert response.status_code == 422
    assert "canonical lowercase" in response.text


def test_magic_bytes_must_match_declared_mime(client, payload):
    encoded = base64.b64encode(IMAGE_MAGIC["image/png"]).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/jpeg;base64,{encoded}"})
    assert response.status_code == 422
    assert "does not match" in response.text


@pytest.mark.parametrize(
    ("mime", "invalid_signature"),
    [
        ("image/jpeg", b"\xff\xd8\x00"),
        ("image/png", b"\x89PNG\r\n\x1a\x00"),
        ("image/webp", b"RIFF\x00\x00\x00\x00WEPB"),
    ],
)
def test_each_format_requires_its_full_signature(client, payload, mime, invalid_signature):
    encoded = base64.b64encode(invalid_signature + b"\x00" * 12).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:{mime};base64,{encoded}"})
    assert response.status_code == 422
    assert "does not match" in response.text


def test_riff_container_that_is_not_webp_is_rejected(client, payload):
    encoded = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVEfmt ").decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/webp;base64,{encoded}"})
    assert response.status_code == 422


def test_encoded_length_is_rejected_before_decode(monkeypatch):
    def fail_if_decoded(*_args, **_kwargs):
        raise AssertionError("oversized payload must not be decoded")

    monkeypatch.setattr("app.photo.base64.b64decode", fail_if_decoded)
    with pytest.raises(ValueError, match="exceeds.*2 MiB"):
        validate_photo_data_url(
            "data:image/png;base64," + "A" * (MAX_PHOTO_BASE64_CHARS + 4)
        )


def test_decoded_image_over_two_mib_is_rejected(client, payload):
    magic = IMAGE_MAGIC["image/png"]
    oversized = magic + b"\x00" * (MAX_PHOTO_BYTES + 1 - len(magic))
    photo = f"data:image/png;base64,{base64.b64encode(oversized).decode()}"
    response = client.post(BASE, json={**payload, "photo": photo})
    assert response.status_code == 422
    assert "2 MiB" in response.text


def test_image_at_the_size_limit_is_accepted(client, payload):
    magic = IMAGE_MAGIC["image/png"]
    exact = magic + b"\x00" * (MAX_PHOTO_BYTES - len(magic))
    photo = f"data:image/png;base64,{base64.b64encode(exact).decode()}"
    assert client.post(BASE, json={**payload, "photo": photo}).status_code == 201


def test_patch_leaves_photo_unchanged_when_omitted(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    body = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"}).json()
    assert body["photo"] == photo


def test_patch_clears_photo_when_explicitly_null(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    body = client.patch(f"{BASE}/{contact_id}", json={"photo": None}).json()
    assert body["photo"] is None


def test_patch_replaces_photo(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    replacement = data_url("image/jpeg")
    body = client.patch(f"{BASE}/{contact_id}", json={"photo": replacement}).json()
    assert body["photo"] == replacement
    assert client.get(f"{BASE}/{contact_id}").json()["photo"] == replacement
    assert client.get(BASE).json()["items"][0]["photo"] == replacement


def test_patch_rejects_an_invalid_photo(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"photo": "data:image/png;base64,%%%%"})
    assert response.status_code == 422
    assert client.get(f"{BASE}/{contact_id}").json()["photo"] == photo


def test_put_clears_photo_when_omitted(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    body = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": None}).json()
    assert body["photo"] is None

    contact_id = client.post(
        BASE, json={**payload, "email": "grace@example.com", "photo": photo}
    ).json()["id"]
    replaced = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    ).json()
    assert replaced["photo"] is None


def test_put_preserves_photo_when_explicitly_sent(client, payload, photo):
    contact_id = client.post(BASE, json={**payload, "photo": photo}).json()["id"]
    body = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": photo}).json()
    assert body["photo"] == photo
    assert client.get(f"{BASE}/{contact_id}").json()["photo"] == photo


def test_put_rejects_an_invalid_photo(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": "data:image/png;base64,zz"})
    assert response.status_code == 422


def test_photo_is_documented_in_the_openapi_schema(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("ContactCreate", "ContactReplace", "ContactUpdate", "ContactRead"):
        photo = schemas[name]["properties"]["photo"]
        assert photo["description"], f"{name}.photo is missing a description"
        assert "image/png" in photo["description"]
        assert "2 MiB" in photo["description"]
        assert "photo" not in schemas[name].get("required", [])
