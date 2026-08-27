from io import BytesIO
from pathlib import Path

from PIL import Image

from app.photo import MAX_IMAGE_BYTES, MAX_MULTIPART_BODY_BYTES

BASE = "/api/v1/contacts"
RANA_IMAGE = Path(__file__).parent / "fixtures" / "Rana.png"


def _create_contact(client, payload) -> int:
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    return response.json()["id"]


def _replacement_image() -> bytes:
    image = Image.new("RGB", (2, 2), color="navy")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_upload_read_replace_and_remove_rana_photo(client, payload):
    contact_id = _create_contact(client, payload)
    rana_image = RANA_IMAGE.read_bytes()

    created = client.get(f"{BASE}/{contact_id}")
    assert created.json()["photo_url"] is None

    uploaded = client.put(
        f"{BASE}/{contact_id}/photo",
        files={"file": ("Rana.png", rana_image, "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["photo_url"] == f"{BASE}/{contact_id}/photo"

    downloaded = client.get(uploaded.json()["photo_url"])
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.content == rana_image

    patched = client.patch(f"{BASE}/{contact_id}", json={"company": "Updated Company"})
    assert patched.status_code == 200
    assert client.get(f"{BASE}/{contact_id}/photo").content == rana_image

    replacement = _replacement_image()
    replaced = client.put(
        f"{BASE}/{contact_id}/photo",
        files={"file": ("replacement.png", replacement, "image/png")},
    )
    assert replaced.status_code == 200
    assert client.get(f"{BASE}/{contact_id}/photo").content == replacement

    assert client.delete(f"{BASE}/{contact_id}/photo").status_code == 204
    assert client.delete(f"{BASE}/{contact_id}/photo").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").json()["photo_url"] is None
    missing_photo = client.get(f"{BASE}/{contact_id}/photo")
    assert missing_photo.status_code == 404
    assert missing_photo.json()["detail"] == f"Contact {contact_id} has no photo"


def test_photo_upload_rejects_unsafe_or_ambiguous_files(client, payload):
    contact_id = _create_contact(client, payload)
    url = f"{BASE}/{contact_id}/photo"

    missing_file = client.put(url)
    assert missing_file.status_code == 422
    assert missing_file.json()["detail"][0]["loc"] == ["body", "file"]

    unsupported = client.put(url, files={"file": ("photo.gif", b"GIF89a", "image/gif")})
    assert unsupported.status_code == 415
    assert "image/jpeg, image/png, or image/webp" in unsupported.json()["detail"]

    mismatched = client.put(url, files={"file": ("Rana.png", RANA_IMAGE.read_bytes(), "image/jpeg")})
    assert mismatched.status_code == 415
    assert "does not match" in mismatched.json()["detail"]

    malformed = client.put(url, files={"file": ("broken.png", b"not an image", "image/png")})
    assert malformed.status_code == 422
    assert malformed.json()["detail"] == "Photo is not a valid image."

    too_large = client.put(url, files={"file": ("large.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")})
    assert too_large.status_code == 413
    assert "2 MiB" in too_large.json()["detail"]

    body_too_large = client.put(
        url,
        files={"file": ("body-too-large.png", b"x" * (MAX_MULTIPART_BODY_BYTES + 1), "image/png")},
    )
    assert body_too_large.status_code == 413
    assert "request exceeds" in body_too_large.json()["detail"]


def test_photo_upload_handles_pillow_bomb_errors(client, payload, monkeypatch):
    contact_id = _create_contact(client, payload)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)

    response = client.put(
        f"{BASE}/{contact_id}/photo",
        files={"file": ("Rana.png", RANA_IMAGE.read_bytes(), "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Photo dimensions exceed the 20 megapixel limit."

def test_contact_json_rejects_implicit_photo_updates(client, payload):
    with_photo = client.post(BASE, json={**payload, "photo": "data:image/png;base64,abc"})
    assert with_photo.status_code == 422
    assert with_photo.json()["detail"][0]["loc"] == ["body", "photo"]

    contact_id = _create_contact(client, payload)
    response = client.patch(f"{BASE}/{contact_id}", json={"photo": None})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "photo"]


def test_photo_operations_require_an_existing_contact(client):
    response = client.put(
        f"{BASE}/9999/photo",
        files={"file": ("Rana.png", RANA_IMAGE.read_bytes(), "image/png")},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Contact 9999 not found"
