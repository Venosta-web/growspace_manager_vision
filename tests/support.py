"""Shared frames, requests, and contract assertions for the service tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import numpy as np
from httpx import Response
from numpy.typing import NDArray
from PIL import Image
from test_growspace_vision_contract import (
    OPENAPI_PATH,
    ContractValidationError,
    OpenApiFixtureValidator,
)

from growspace_vision.images import DecodedImage

ROOT = Path(__file__).parents[1]
FIXTURE_DIR = ROOT / "contracts" / "growspace-vision" / "v1" / "fixtures"

MODEL_ID = "dinov2-vit-s-14-int8-onnx"
MODEL_VERSION = "1.0.0"
EMBEDDING_DIMENSION = 384

BEARER = {"Authorization": "Bearer test-secret"}

REMOVED = object()


def load_fixture(name: str) -> dict[str, Any]:
    """Load an independently maintained normative contract fixture."""

    return load_contract_fixture(f"valid/{name}")


def load_contract_fixture(relative_path: str) -> dict[str, Any]:
    """Load one fixture by its manifest-relative path."""

    return cast(
        dict[str, Any],
        json.loads((FIXTURE_DIR / relative_path).read_text(encoding="utf-8")),
    )


class ReadyAnalyzer:
    """Test stand-in for the model runtime the DINOv2 ticket supplies."""

    ready = True
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    embedding_dimension = EMBEDDING_DIMENSION

    def __init__(self) -> None:
        self.embedded: list[DecodedImage] = []

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        self.embedded.append(image)
        return [0.0] * EMBEDDING_DIMENSION


def gray_frame(values: NDArray[np.integer[Any]]) -> bytes:
    """Encode an 8-bit grey pattern losslessly, so decoded pixels are exactly it.

    A grey frame's BT.601 luminance equals its channel value, which is what makes
    the thresholds below expressible as exact numbers rather than approximations.
    """

    plane = np.asarray(values, dtype=np.uint8)
    rgb = np.repeat(plane[:, :, None], 3, axis=2)
    return encode(rgb, "PNG")


def encode(pixels: NDArray[np.uint8], image_format: str) -> bytes:
    """Encode decoded RGB pixels in one of the supported wire formats."""

    buffer = BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format=image_format)
    return buffer.getvalue()


def striped_frame(dark: int, light: int, *, size: int = 64) -> bytes:
    """Alternate two values by column: mean is their average, gradient their gap/2."""

    column = np.where(np.arange(size) % 2 == 0, dark, light)
    return gray_frame(np.tile(column, (size, 1)))


def uniform_frame(value: int, *, size: int = 64) -> bytes:
    """A frame with no spatial variation at all: a lens cap, a wall, a dead sensor."""

    return gray_frame(np.full((size, size), value))


def clipped_frame(clipped_rows: int) -> bytes:
    """A 100x100 frame with an exact fraction of its pixels above the clipping level."""

    plane = np.full((100, 100), 100)
    plane[:clipped_rows, :] = 250
    return gray_frame(plane)


def usable_frame() -> bytes:
    """A frame comfortably inside every absolute floor."""

    return striped_frame(120, 160)


def metadata_json(**overrides: Any) -> str:
    """Render request metadata from the normative fixture, with edits."""

    metadata = load_fixture("analyze-metadata.json")
    for field, value in overrides.items():
        if value is REMOVED:
            metadata.pop(field, None)
        else:
            metadata[field] = value
    return json.dumps(metadata)


def analyze_request(
    image: bytes,
    *,
    light_state: str = "on",
    metadata: str | None = None,
    filename: str = "frame.png",
    content_type: str = "image/png",
) -> dict[str, Any]:
    """Build the multipart request keyword arguments for one Vision Analysis."""

    body = metadata_json(light_state=light_state) if metadata is None else metadata
    return {
        "data": {"metadata": body},
        "files": {"image": (filename, image, content_type)},
    }


def assert_matches_contract_response(
    response: Response, path: str, method: str
) -> None:
    """Validate one live HTTP response against its normative OpenAPI operation."""

    document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    validator = OpenApiFixtureValidator(document)
    responses = document["paths"][path][method]["responses"]
    status = str(response.status_code)
    if status not in responses:
        raise ContractValidationError(
            f"{method.upper()} {path} returned undeclared status {status}"
        )
    response_spec = responses[status]
    if "$ref" in response_spec:
        response_spec = validator._resolve(response_spec["$ref"])
    media_type = response.headers.get("content-type", "").partition(";")[0]
    if media_type != "application/json":
        raise ContractValidationError(
            f"{method.upper()} {path} returned {media_type!r}, "
            "expected application/json"
        )
    schema = response_spec["content"]["application/json"]["schema"]
    validator.validate(response.json(), schema)

    for name, header_spec in response_spec.get("headers", {}).items():
        if name not in response.headers:
            raise ContractValidationError(
                f"{method.upper()} {path} omitted declared response header {name}"
            )
        value: Any = response.headers[name]
        if header_spec["schema"].get("type") == "integer":
            try:
                value = int(value)
            except ValueError as error:
                raise ContractValidationError(
                    f"{method.upper()} {path} returned non-integer header {name}"
                ) from error
        validator.validate(value, header_spec["schema"], f"$.headers.{name}")
