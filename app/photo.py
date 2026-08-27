"""Validate contact photos stored as base64 data URLs."""

import base64
import binascii
import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

MAX_PHOTO_BYTES = 2 * 1024 * 1024
"""Largest decoded image accepted, in bytes (2 MiB)."""

# Standard base64 expands 3 bytes into 4 characters. Checking the encoded length
# first lets us reject an oversized payload without allocating its decoded form.
MAX_PHOTO_BASE64_CHARS = 4 * ((MAX_PHOTO_BYTES + 2) // 3)
MAX_PHOTO_DATA_URL_CHARS = MAX_PHOTO_BASE64_CHARS + len("data:image/jpeg;base64,")

# Leading bytes that identify each accepted format. WebP needs a second check
# because "RIFF" also introduces WAV and AVI containers.
_MAGIC_BYTES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
ALLOWED_PHOTO_MIME_TYPES = tuple(sorted(_MAGIC_BYTES))

_DATA_URL = re.compile(
    r"data:(?P<mime>[A-Za-z0-9][A-Za-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*);"
    r"base64,(?P<payload>.*)",
    re.DOTALL,
)

PHOTO_DESCRIPTION = (
    "Profile photo as a base64 image data URL: `data:<mime>;base64,<payload>`. "
    f"Allowed MIME types are {', '.join(f'`{mime}`' for mime in ALLOWED_PHOTO_MIME_TYPES)}. "
    "The payload must be canonical, correctly padded standard base64; the decoded "
    "image must be non-empty, at most 2 MiB, and start with magic bytes matching the "
    "declared MIME type. The value is `null` when the contact has no photo."
)
PHOTO_UPDATE_DESCRIPTION = (
    f"{PHOTO_DESCRIPTION} Omit this field to keep the current photo; send `null` to remove it."
)
PHOTO_EXAMPLE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _matches_magic_bytes(mime: str, image: bytes) -> bool:
    if not image.startswith(_MAGIC_BYTES[mime]):
        return False
    if mime == "image/webp":
        return image[8:12] == b"WEBP"
    return True


def validate_photo_data_url(value: str) -> str:
    """Return `value` unchanged if it is a supported image data URL, else raise."""
    match = _DATA_URL.fullmatch(value)
    if match is None:
        raise ValueError("photo must be a data URL of the form data:<mime>;base64,<payload>")

    mime = match["mime"]
    normalized_mime = mime.lower()
    if normalized_mime not in _MAGIC_BYTES:
        raise ValueError(
            f"unsupported image type '{mime}'; allowed types are {', '.join(ALLOWED_PHOTO_MIME_TYPES)}"
        )
    if mime != normalized_mime:
        raise ValueError("photo MIME type must use canonical lowercase spelling")

    payload = match["payload"]
    if not payload:
        raise ValueError("photo image data is empty")
    if len(payload) > MAX_PHOTO_BASE64_CHARS:
        raise ValueError(
            f"photo exceeds the maximum decoded size of {MAX_PHOTO_BYTES // 1024 // 1024} MiB"
        )

    try:
        image = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"photo is not valid base64: {exc}") from exc

    if base64.b64encode(image).decode() != payload:
        raise ValueError("photo must use canonical base64 encoding")
    if len(image) > MAX_PHOTO_BYTES:
        raise ValueError(
            f"photo exceeds the maximum decoded size of {MAX_PHOTO_BYTES // 1024 // 1024} MiB"
        )
    if not _matches_magic_bytes(mime, image):
        raise ValueError(f"photo content does not match the declared image type '{mime}'")

    return value


PhotoDataUrl = Annotated[
    str,
    StringConstraints(max_length=MAX_PHOTO_DATA_URL_CHARS),
    AfterValidator(validate_photo_data_url),
]
"""Request-side type for a validated image data URL."""
