import mimetypes
import secrets
from pathlib import PurePath

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _extension_for_name(original_name):
    suffix = PurePath(original_name or "").suffix.lower()
    return ".jpg" if suffix == ".jpeg" else suffix


def validate_uploaded_image(file_obj):
    if not getattr(settings, "MEDIA_UPLOADS_ENABLED", True):
        raise ValidationError(
            "Production media storage is not configured. Set MEDIA_STORAGE_BACKEND and external media settings before enabling uploads."
        )

    original_name = getattr(file_obj, "name", "")
    extension = _extension_for_name(original_name)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("Only JPEG, PNG, and WEBP images are allowed.")

    content_type = getattr(file_obj, "content_type", "") or mimetypes.guess_type(original_name)[0]
    if content_type not in ALLOWED_MIME_TYPES:
        raise ValidationError("The uploaded file type is not allowed.")

    max_size = getattr(settings, "AURAFOODS_MAX_UPLOAD_BYTES", 3 * 1024 * 1024)
    size = getattr(file_obj, "size", 0)
    if size and size > max_size:
        raise ValidationError("The uploaded image is too large.")

    position = file_obj.tell() if hasattr(file_obj, "tell") else None
    try:
        image = Image.open(file_obj)
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError("The uploaded file is not a valid image.") from exc
    finally:
        if hasattr(file_obj, "seek"):
            file_obj.seek(position or 0)

    return True


def safe_uploaded_image_name(original_name, prefix=None):
    extension = _extension_for_name(original_name)
    if extension not in ALLOWED_EXTENSIONS:
        extension = ".jpg"
    clean_prefix = "".join(ch for ch in str(prefix or "uploads") if ch.isalnum() or ch in {"-", "_"})
    clean_prefix = clean_prefix.strip("-_") or "uploads"
    return f"{clean_prefix}/{secrets.token_hex(16)}{extension}"


def save_uploaded_image(file_obj, folder_or_prefix):
    validate_uploaded_image(file_obj)
    relative_name = safe_uploaded_image_name(getattr(file_obj, "name", ""), folder_or_prefix)
    saved_name = default_storage.save(relative_name, file_obj)
    return default_storage.url(saved_name)
