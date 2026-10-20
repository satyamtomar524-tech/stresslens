"""One explicitly selected still in the current app session; no timers or I/O."""
import io
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image, ImageOps, UnidentifiedImageError

from stresslens.face import MAX_BYTES, MAX_PIXELS


@dataclass(frozen=True)
class PersonalPhoto:
    data: bytes
    source: str
    selected_at: datetime
    revision: int


def utc_now():
    return datetime.now(UTC)


def get_photo(state):
    return state.get("personal_photo")


def photo_revision(state):
    return state.get("personal_photo_revision", 0)


def choose_photo(state, data, *, source, expected_revision=None):
    """Validate before replacing; an old uploader callback cannot resurrect a choice."""
    if expected_revision is not None and expected_revision != photo_revision(state):
        return False
    if source not in {"upload", "camera"}:
        raise ValueError("Choose a photo from an upload or an explicit camera snapshot.")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Choose a supported photo smaller than 40 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Use a PNG, JPEG or WebP photo.")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("Use a photo below 20 megapixels.")
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.info.clear()  # Do not retain EXIF, GPS, filenames or embedded text.
                output = io.BytesIO()
                image.save(output, format="PNG")
                if output.tell() > MAX_BYTES:
                    raise ValueError("The decoded photo is too large. Choose a smaller image; your previous choice is unchanged.")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("This file could not be read as a supported photo. Your previous choice is unchanged.") from exc
    revision = photo_revision(state) + 1
    state["personal_photo"] = PersonalPhoto(output.getvalue(), source, utc_now(), revision)
    state["personal_photo_revision"] = revision
    state.pop("analysis", None)
    return True


def remove_photo(state):
    state.pop("personal_photo", None)
    state["personal_photo_revision"] = photo_revision(state) + 1
    state.pop("analysis", None)


def capture_selection(state, camera, *, consented):
    if not consented:
        raise ValueError("Start the camera yourself after reviewing face privacy before capturing a still.")
    rgb = camera.capture_photo()  # Read-only detached frame; never starts a device.
    output = io.BytesIO()
    Image.fromarray(rgb).save(output, format="PNG")
    return choose_photo(state, output.getvalue(), source="camera")


def commit_analysis(state, result, *, expected_revision):
    """Drop a delayed completion if another action replaced/removed its photo."""
    if expected_revision != photo_revision(state):
        return False
    photo = get_photo(state)
    result = dict(result)
    example = result.get("example", False)
    result["photo_revision"] = None if example else expected_revision
    result["photo"] = ({"source": photo.source, "selected_at_utc": photo.selected_at.isoformat()}
                       if photo and not example and result.get("media_source") == "selected_photo" else None)
    state["analysis"] = result
    return True
