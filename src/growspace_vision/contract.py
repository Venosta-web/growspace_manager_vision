"""V1 response builders kept aligned with the normative wire contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from growspace_vision.quality import QualitySignals


def build_info_response(service_version: str) -> dict[str, Any]:
    """Return the frozen V1 negotiation response."""

    return {
        "schema_version": 1,
        "service_name": "growspace_manager_vision",
        "service_version": service_version,
        "supported_schema_versions": [1],
        "capabilities": {
            "single_image_analysis": True,
            "batch_analysis": False,
            "embeddings": True,
            "service_scoring": False,
            "regions": False,
        },
        "limits": {
            "max_image_bytes": 10_485_760,
            "max_decoded_pixels": 24_000_000,
            "max_concurrency": 1,
            "max_queue_depth": 0,
            "inference_timeout_seconds": 10,
        },
    }


def build_models_response(
    *,
    model_id: str,
    model_version: str,
    embedding_dimension: int,
    ready: bool,
) -> dict[str, Any]:
    """Return the bundled model descriptor for V1."""

    return {
        "schema_version": 1,
        "models": [
            {
                "model_id": model_id,
                "model_version": model_version,
                "embedding_dimension": embedding_dimension,
                "state": "loaded" if ready else "unavailable",
            }
        ],
    }


def build_analyzed_response(
    *,
    request_id: str,
    model_id: str,
    model_version: str,
    embedding: Sequence[float],
    signals: QualitySignals,
) -> dict[str, Any]:
    """Return the accepted V1 result: one embedding and its quality evidence."""

    return {
        "schema_version": 1,
        "request_id": request_id,
        "status": "analyzed",
        "model": {"model_id": model_id, "model_version": model_version},
        "embedding": {"dimension": len(embedding), "values": list(embedding)},
        "quality": {"signals": signals.as_contract(), "reasons": []},
        "regions": [],
    }


def build_rejected_response(
    *,
    request_id: str,
    signals: QualitySignals,
    reasons: Sequence[str],
) -> dict[str, Any]:
    """Return the rejected V1 result, which is an outcome rather than a failure.

    It carries no embedding and no model identity: nothing was inferred, and Home
    Assistant must not be able to treat an Unusable Capture as a comparable one.
    """

    return {
        "schema_version": 1,
        "request_id": request_id,
        "status": "rejected",
        "quality": {"signals": signals.as_contract(), "reasons": list(reasons)},
        "regions": [],
    }
