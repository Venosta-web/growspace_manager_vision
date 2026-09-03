"""Validation of the only non-image observation the V1 contract permits.

`AnalyzeMetadata` is a closed object. Anything the contract does not name — an
environmental reading in particular — is refused rather than ignored, because a
field the service silently drops is a boundary the integration can drift across.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

LightState = Literal["on", "off", "unknown"]

SUPPORTED_SCHEMA_VERSION: Final = 1

_LIGHT_STATES: Final[tuple[LightState, ...]] = ("on", "off", "unknown")
_MAX_CORRELATION_LENGTH: Final = 255
_MAX_MODEL_FIELD_LENGTH: Final = 128
_PERMITTED_FIELDS: Final = frozenset(
    {
        "schema_version",
        "camera_id",
        "growspace_id",
        "captured_at",
        "light_state",
        "model_id",
        "model_version",
    }
)


class InvalidMetadata(ValueError):
    """The metadata part is absent, malformed, or outside the closed contract."""


class UnsupportedSchemaVersion(ValueError):
    """The metadata announces an analysis schema this service does not implement."""


@dataclass(frozen=True, slots=True)
class AnalyzeMetadata:
    """One request's validated metadata, held only for the life of the request."""

    camera_id: str
    growspace_id: str
    captured_at: datetime
    light_state: LightState
    model_id: str
    model_version: str


def parse_metadata(raw: bytes) -> AnalyzeMetadata:
    """Parse and validate the metadata part of one Vision Analysis request."""

    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidMetadata("Metadata is not valid JSON") from error
    if not isinstance(document, dict):
        raise InvalidMetadata("Metadata must be a JSON object")

    _require_supported_schema_version(document)
    _require_exactly_the_permitted_fields(document)
    return AnalyzeMetadata(
        camera_id=_bounded_text(document, "camera_id", _MAX_CORRELATION_LENGTH),
        growspace_id=_bounded_text(document, "growspace_id", _MAX_CORRELATION_LENGTH),
        captured_at=_utc_timestamp(document, "captured_at"),
        light_state=_light_state(document, "light_state"),
        model_id=_bounded_text(document, "model_id", _MAX_MODEL_FIELD_LENGTH),
        model_version=_bounded_text(document, "model_version", _MAX_MODEL_FIELD_LENGTH),
    )


def _require_supported_schema_version(document: dict[str, Any]) -> None:
    """Negotiate before validating, so a future schema reports itself as one."""

    if "schema_version" not in document:
        raise InvalidMetadata("Metadata is missing schema_version")
    version = document["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise InvalidMetadata("Metadata schema_version must be an integer")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion("Schema version is unsupported")


def _require_exactly_the_permitted_fields(document: dict[str, Any]) -> None:
    if unsupported := set(document) - _PERMITTED_FIELDS:
        raise InvalidMetadata(
            f"Metadata carries {len(unsupported)} field(s) outside the contract"
        )
    if _PERMITTED_FIELDS - set(document):
        raise InvalidMetadata("Metadata is missing required fields")


def _bounded_text(document: dict[str, Any], field: str, limit: int) -> str:
    value = document[field]
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise InvalidMetadata(f"Metadata {field} is not a bounded string")
    return value


def _light_state(document: dict[str, Any], field: str) -> LightState:
    value = document[field]
    for state in _LIGHT_STATES:
        if value == state:
            return state
    raise InvalidMetadata(f"Metadata {field} is not a known light state")


def _utc_timestamp(document: dict[str, Any], field: str) -> datetime:
    """Require the contract's UTC RFC 3339 form rather than any ISO 8601 string."""

    value = document[field]
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InvalidMetadata(f"Metadata {field} is not a UTC RFC 3339 timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidMetadata(
            f"Metadata {field} is not a UTC RFC 3339 timestamp"
        ) from error
