from pathlib import Path

import pytest

from app import avatar

BASE = "/api/v1/contacts"

SOURCE_PHOTO = (Path(__file__).parent / "fixtures" / "Rana.png").read_bytes()
GENERATED_PHOTO = SOURCE_PHOTO


def add_photo(client, contact_id: int) -> None:
    response = client.put(
        f"{BASE}/{contact_id}/photo",
        files={"file": ("source.png", SOURCE_PHOTO, "image/png")},
    )
    assert response.status_code == 200, response.text


def test_generate_avatar_replaces_photo_and_passes_gender(
    client, payload, monkeypatch
):
    contact = client.post(BASE, json={**payload, "gender": "female"}).json()
    add_photo(client, contact["id"])
    seen = {}

    def generate(photo, content_type, gender, settings):
        seen.update(
            photo=photo,
            content_type=content_type,
            gender=gender,
            settings=settings,
        )
        return GENERATED_PHOTO, "image/png"

    monkeypatch.setattr(avatar, "generate_avatar", generate)

    response = client.post(f"{BASE}/{contact['id']}/generate-avatar")

    assert response.status_code == 200, response.text
    assert response.json()["photo_url"] == f"{BASE}/{contact['id']}/photo"
    assert response.json()["gender"] == "female"
    assert client.get(response.json()["photo_url"]).content == GENERATED_PHOTO
    assert seen["photo"] == SOURCE_PHOTO
    assert seen["content_type"] == "image/png"
    assert seen["gender"].value == "female"


def test_generate_avatar_requires_a_source_photo(client, payload, monkeypatch):
    contact_id = client.post(BASE, json=payload).json()["id"]
    generate = monkeypatch.setattr(
        avatar,
        "generate_avatar",
        lambda *_args: pytest.fail("generation must not run without a photo"),
    )

    response = client.post(f"{BASE}/{contact_id}/generate-avatar")

    assert generate is None
    assert response.status_code == 409
    assert "photo" in response.json()["detail"].lower()


def test_generate_avatar_returns_404_for_missing_contact(client, monkeypatch):
    monkeypatch.setattr(
        avatar,
        "generate_avatar",
        lambda *_args: pytest.fail("generation must not run for a missing contact"),
    )

    assert client.post(f"{BASE}/9999/generate-avatar").status_code == 404


def test_configuration_failure_is_actionable_and_does_not_leak(
    client, payload, monkeypatch
):
    contact = client.post(BASE, json=payload).json()
    add_photo(client, contact["id"])

    def fail(*_args):
        raise avatar.AvatarConfigurationError("secret-key-value")

    monkeypatch.setattr(avatar, "generate_avatar", fail)

    response = client.post(f"{BASE}/{contact['id']}/generate-avatar")

    assert response.status_code == 503
    assert "configuration" in response.json()["detail"].lower()
    assert "secret-key-value" not in response.text
    assert client.get(f"{BASE}/{contact['id']}/photo").content == SOURCE_PHOTO


def test_upstream_failure_preserves_the_source_photo(client, payload, monkeypatch):
    contact = client.post(BASE, json=payload).json()
    add_photo(client, contact["id"])

    def fail(*_args):
        raise avatar.AvatarGenerationError("upstream response included private detail")

    monkeypatch.setattr(avatar, "generate_avatar", fail)

    response = client.post(f"{BASE}/{contact['id']}/generate-avatar")

    assert response.status_code == 502
    assert response.json()["detail"] == "Avatar generation failed. Try again."
    assert "private detail" not in response.text
    assert client.get(f"{BASE}/{contact['id']}/photo").content == SOURCE_PHOTO


def test_generate_avatar_operation_is_documented(client):
    operation = client.get("/openapi.json").json()["paths"][
        f"{BASE}/{{contact_id}}/generate-avatar"
    ]["post"]

    assert operation["operationId"] == "generateContactAvatar"
    assert set(operation["responses"]) >= {"200", "404", "409", "502", "503"}
