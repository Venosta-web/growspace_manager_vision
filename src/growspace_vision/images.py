"""Deterministic decoding of one Camera Snapshot at the edge of the service."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES: Final = 10 * 1024 * 1024
MAX_DECODED_PIXELS: Final = 24_000_000
SUPPORTED_IMAGE_FORMATS: Final = frozenset({"JPEG", "PNG"})


class ImageRejected(Exception):
    """Base for image bodies the service refuses before any measurement."""


class UnsupportedImageFormat(ImageRejected):
    """The body is not a JPEG or a PNG."""


class ImageTooLarge(ImageRejected):
    """The encoded body or its decoded pixel count exceeds a locked limit."""


class UndecodableImage(ImageRejected):
    """The body announces a supported format but does not decode."""


@dataclass(frozen=True, slots=True)
class DecodedImage:
    """Full-resolution 8-bit RGB pixels: the only image form the service analyses."""

    pixels: NDArray[np.uint8]

    @property
    def width(self) -> int:
        """Return the decoded width in pixels."""

        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        """Return the decoded height in pixels."""

        return int(self.pixels.shape[0])


def decode_image(body: bytes) -> DecodedImage:
    """Decode one encoded snapshot, refusing anything outside the locked limits.

    Decoding is deliberately literal: no EXIF orientation, no colour management and
    no resampling. Every downstream measurement is defined on these exact pixels —
    the quality signals here, and the model preprocessing that follows them — so a
    decoder that helpfully corrected a frame would silently change both.
    """

    if len(body) > MAX_IMAGE_BYTES:
        raise ImageTooLarge("Encoded image exceeds the service limit")
    if not body:
        raise UndecodableImage("Image body is empty")
    try:
        with Image.open(BytesIO(body)) as image:
            if image.format not in SUPPORTED_IMAGE_FORMATS:
                raise UnsupportedImageFormat("Image is not JPEG or PNG")
            width, height = image.size
            if width * height > MAX_DECODED_PIXELS:
                raise ImageTooLarge("Decoded image exceeds the service limit")
            pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    except UnidentifiedImageError as error:
        raise UnsupportedImageFormat("Image is not JPEG or PNG") from error
    except Image.DecompressionBombError as error:
        raise ImageTooLarge("Decoded image exceeds the service limit") from error
    except (OSError, ValueError) as error:
        raise UndecodableImage("Image could not be decoded") from error
    return DecodedImage(pixels=pixels)
