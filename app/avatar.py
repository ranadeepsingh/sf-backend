"""Generate an original cartoon contact avatar with Azure OpenAI.

The request and response handling is adapted from the generate-images skill:
credentials stay in environment-backed settings, redirects are rejected, error
details are bounded and redacted, and only base64 image responses are accepted.
"""

from __future__ import annotations

import base64
import binascii
import http.client
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from app.config import Settings
from app.gender import Gender
from app.photo import ImageValidationError, validate_image_bytes

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
HTTP_ERROR_DETAIL_LIMIT = 1_000

_OUTPUT_MIME_TYPES = {
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_INPUT_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_UNKNOWN_PRESENTATIONS = (
    "Balance soft and angular facial shapes with a neutral hairstyle.",
    "Mix subtle masculine and feminine design cues without leaning toward either.",
    "Use an androgynous silhouette and a fresh, randomly chosen neutral styling.",
)

_BASE_PROMPT = """
Transform the supplied portrait into an original, polished 2D animated-sitcom
avatar. Preserve recognizable facial structure, hair, eyewear, facial hair,
expression, and clothing cues from the source photo. Use an American
prime-time animated-sitcom aesthetic with a distinctly stylized sunny
golden-yellow complexion, bold clean dark outlines, simple rounded geometric
forms, large expressive eyes, flat saturated colors, minimal cel shading, a
shoulders-up composition, and a plain sky-blue background. Keep the result
friendly and professional. Do not add
text, logos, watermarks, existing TV-show settings, copyrighted characters, or
trademarked visual elements. Do not imitate a specific living artist.
""".strip()


class AvatarConfigurationError(RuntimeError):
    """The server is missing or has invalid image-service configuration."""


class AvatarGenerationError(RuntimeError):
    """The configured image service failed or returned an unusable image."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward the API key to a redirected origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def build_avatar_prompt(
    gender: Gender,
    *,
    choose: Callable[[Sequence[str]], str] | None = None,
) -> str:
    if gender is Gender.MALE:
        guidance = (
            "Keep the person recognizably masculine-presenting without "
            "exaggerating gender stereotypes."
        )
    elif gender is Gender.FEMALE:
        guidance = (
            "Keep the person recognizably feminine-presenting without "
            "exaggerating gender stereotypes."
        )
    else:
        direction = (choose or secrets.choice)(_UNKNOWN_PRESENTATIONS)
        guidance = (
            "Use a gender-neutral, deliberately androgynous presentation that "
            f"stays between masculine and feminine. {direction}"
        )
    return f"{_BASE_PROMPT}\n\nPresentation guidance: {guidance}"


def _normalize_endpoint(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port
    except ValueError as error:
        raise AvatarConfigurationError("Image endpoint is not a valid URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise AvatarConfigurationError(
            "Image endpoint must be an HTTPS base URL without credentials or a path."
        )
    return value


def _edit_url(settings: Settings) -> str:
    if not settings.image_endpoint:
        raise AvatarConfigurationError("Image endpoint is not configured.")
    deployment = urllib.parse.quote(settings.image_deployment, safe="")
    api_version = urllib.parse.quote(settings.image_api_version, safe="")
    return (
        f"{_normalize_endpoint(settings.image_endpoint)}/openai/deployments/"
        f"{deployment}/images/edits?api-version={api_version}"
    )


def _api_key(settings: Settings) -> str:
    if settings.image_api_key is None:
        raise AvatarConfigurationError("Image API key is not configured.")
    key = settings.image_api_key.get_secret_value()
    if (
        not key
        or key != key.strip()
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or ord(character) > 0xFF
            for character in key
        )
    ):
        raise AvatarConfigurationError("Image API key has an invalid format.")
    return key


def _multipart_body(
    *,
    prompt: str,
    image_mime: str,
    image: bytes,
    settings: Settings,
) -> tuple[str, bytes]:
    boundary = f"----sfcontacts-{secrets.token_hex(16)}"
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )

    field("prompt", prompt)
    field("n", "1")
    field("size", settings.image_size)
    field("quality", settings.image_quality)
    field("output_format", settings.image_output_format)

    extension = _INPUT_EXTENSIONS[image_mime]
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="image"; '
                f'filename="contact.{extension}"\r\n'
            ).encode(),
            f"Content-Type: {image_mime}\r\n\r\n".encode(),
            image,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return boundary, b"".join(chunks)


def _sanitize_detail(detail: object, api_key: str) -> str:
    return str(detail).replace(api_key, "[REDACTED]")[:HTTP_ERROR_DETAIL_LIMIT]


def _request_edit(
    *,
    url: str,
    api_key: str,
    boundary: str,
    body: bytes,
    timeout: int,
    opener: Any | None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "api-key": api_key,
        },
    )
    client = opener or urllib.request.build_opener(NoRedirectHandler())
    try:
        with client.open(request, timeout=timeout) as response:
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_RESPONSE_BYTES:
                raise AvatarGenerationError("Image response exceeded the size limit.")
    except urllib.error.HTTPError as error:
        try:
            detail = error.read(HTTP_ERROR_DETAIL_LIMIT + 1).decode(
                "utf-8", errors="replace"
            )
        except http.client.HTTPException:
            detail = ""
        safe_detail = _sanitize_detail(detail, api_key).strip()
        suffix = f": {safe_detail}" if safe_detail else ""
        raise AvatarGenerationError(
            f"Image edit failed with HTTP {error.code}{suffix}"
        ) from error
    except urllib.error.URLError as error:
        detail = _sanitize_detail(error.reason, api_key)
        raise AvatarGenerationError(f"Image edit request failed: {detail}") from error
    except http.client.HTTPException as error:
        detail = _sanitize_detail(error, api_key)
        raise AvatarGenerationError(f"Image edit response failed: {detail}") from error

    try:
        parsed = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AvatarGenerationError("Image endpoint returned invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise AvatarGenerationError("Image endpoint returned an unexpected JSON value.")
    return parsed


def _image_bytes(response: dict[str, Any]) -> bytes:
    data = response.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise AvatarGenerationError("Image response did not contain an image.")
    item = data[0]
    encoded = item.get("b64_json") or item.get("image") or item.get("base64")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise AvatarGenerationError(
                "Image endpoint returned invalid base64 data."
            ) from error
    if item.get("url"):
        raise AvatarGenerationError(
            "Image endpoint returned a URL instead of base64 image data."
        )
    raise AvatarGenerationError("Image response did not contain base64 image data.")


def generate_avatar(
    photo: bytes,
    photo_content_type: str,
    gender: Gender,
    settings: Settings,
    *,
    opener: Any | None = None,
) -> tuple[bytes, str]:
    """Transform a stored contact photo and return validated image bytes."""
    url = _edit_url(settings)
    api_key = _api_key(settings)
    boundary, body = _multipart_body(
        prompt=build_avatar_prompt(gender),
        image_mime=photo_content_type,
        image=photo,
        settings=settings,
    )
    response = _request_edit(
        url=url,
        api_key=api_key,
        boundary=boundary,
        body=body,
        timeout=settings.image_timeout_seconds,
        opener=opener,
    )
    output_mime = _OUTPUT_MIME_TYPES[settings.image_output_format]
    generated = _image_bytes(response)
    try:
        validate_image_bytes(generated, declared_content_type=output_mime)
    except ImageValidationError as error:
        raise AvatarGenerationError(
            f"Generated avatar cannot be stored: {error}"
        ) from error
    return generated, output_mime
