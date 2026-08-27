from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_MEDIA_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class ImageValidationError(ValueError):
    """An uploaded image cannot be accepted."""

    def __init__(self, message: str, *, media_type_error: bool = False) -> None:
        super().__init__(message)
        self.media_type_error = media_type_error


def validate_image_bytes(data: bytes, *, declared_content_type: str) -> str:
    """Return the verified media type when bytes match the declared supported image."""
    if not data:
        raise ImageValidationError("Photo file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError(f"Photo exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit.")

    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ImageValidationError("Photo is not a valid image.") from error

    detected_content_type = SUPPORTED_MEDIA_TYPES.get(image_format or "")
    if detected_content_type is None:
        raise ImageValidationError("Photo must be a JPEG, PNG, or WebP image.", media_type_error=True)
    if detected_content_type != declared_content_type:
        raise ImageValidationError("Photo Content-Type does not match the image format.", media_type_error=True)
    if not width or not height or width * height > MAX_IMAGE_PIXELS:
        raise ImageValidationError("Photo dimensions exceed the 20 megapixel limit.")
    return detected_content_type
