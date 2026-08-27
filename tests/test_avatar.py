import base64
from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import SecretStr

from app.avatar import (
    AvatarConfigurationError,
    AvatarGenerationError,
    build_avatar_prompt,
    generate_avatar,
)
from app.config import Settings
from app.gender import Gender


SOURCE_BYTES = (Path(__file__).parent / "fixtures" / "Rana.png").read_bytes()
output = BytesIO()
Image.new("RGB", (4, 4), "gold").save(output, format="JPEG")
OUTPUT_BYTES = output.getvalue()


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int):
        return self.payload


class FakeOpener:
    def __init__(self, payload: dict):
        self.payload = payload
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return FakeResponse(self.payload)


def settings(**overrides) -> Settings:
    values = {
        "image_endpoint": "https://images.example.openai.azure.com",
        "image_api_key": SecretStr("test-api-key"),
        "image_deployment": "gpt-image-2",
        "image_api_version": "2025-04-01-preview",
        "image_size": "1024x1024",
        "image_quality": "medium",
        "image_output_format": "jpeg",
        "image_timeout_seconds": 45,
    }
    return Settings(**{**values, **overrides})


@pytest.mark.parametrize(
    ("gender", "guidance"),
    [
        (Gender.MALE, "masculine-presenting"),
        (Gender.FEMALE, "feminine-presenting"),
    ],
)
def test_gender_prompt_guidance(gender, guidance):
    prompt = build_avatar_prompt(gender)

    assert guidance in prompt
    assert "original" in prompt.lower()
    assert "copyrighted character" in prompt.lower()
    assert "Simpsons" not in prompt


def test_unknown_gender_uses_a_randomized_androgynous_direction():
    selected = []

    def choose(options):
        selected.append(tuple(options))
        return options[-1]

    prompt = build_avatar_prompt(Gender.UNKNOWN, choose=choose)

    assert selected
    assert "gender-neutral" in prompt
    assert selected[0][-1] in prompt


def test_generate_avatar_sends_a_multipart_edit_and_returns_validated_bytes():
    encoded = base64.b64encode(OUTPUT_BYTES).decode()
    opener = FakeOpener({"data": [{"b64_json": encoded}]})

    result = generate_avatar(
        SOURCE_BYTES,
        "image/png",
        Gender.FEMALE,
        settings(),
        opener=opener,
    )

    assert result == (OUTPUT_BYTES, "image/jpeg")
    assert opener.timeout == 45
    assert opener.request.full_url.endswith(
        "/openai/deployments/gpt-image-2/images/edits"
        "?api-version=2025-04-01-preview"
    )
    assert opener.request.get_header("Api-key") == "test-api-key"
    content_type = opener.request.get_header("Content-type")
    assert content_type.startswith("multipart/form-data; boundary=")
    body = opener.request.data
    assert SOURCE_BYTES in body
    assert b'name="image"; filename="contact.png"' in body
    assert b'name="prompt"' in body
    assert b'name="output_format"' in body
    assert b"\r\n\r\njpeg\r\n" in body


def test_generate_avatar_requires_endpoint_and_key():
    with pytest.raises(AvatarConfigurationError):
        generate_avatar(
            SOURCE_BYTES,
            "image/png",
            Gender.UNKNOWN,
            settings(image_endpoint=None),
        )
    with pytest.raises(AvatarConfigurationError):
        generate_avatar(
            SOURCE_BYTES,
            "image/png",
            Gender.UNKNOWN,
            settings(image_api_key=None),
        )


def test_generate_avatar_rejects_url_only_responses():
    opener = FakeOpener({"data": [{"url": "https://example.test/generated.png"}]})

    with pytest.raises(AvatarGenerationError, match="base64"):
        generate_avatar(
            SOURCE_BYTES,
            "image/png",
            Gender.MALE,
            settings(),
            opener=opener,
        )
