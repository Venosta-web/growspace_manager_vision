"""Boundary between HTTP orchestration and model inference."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from threading import Lock
from typing import Any, Protocol

from growspace_vision.contract import (
    build_analyzed_response,
    build_rejected_response,
)
from growspace_vision.images import DecodedImage, decode_image
from growspace_vision.metadata import AnalyzeMetadata
from growspace_vision.quality import frame_quality_reasons, measure_quality_signals


class Analyzer(Protocol):
    """Model runtime exposed to the stateless HTTP application."""

    @property
    def ready(self) -> bool:
        """Whether this runtime can accept Vision Analyses."""

    @property
    def model_id(self) -> str:
        """Return the contract model identity."""

    @property
    def model_version(self) -> str:
        """Return the exact model artifact version."""

    @property
    def embedding_dimension(self) -> int:
        """Return the output vector dimension."""

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        """Embed one frame the Frame Quality Gate has already accepted."""


class UnavailableAnalyzer:
    """Startup state used until a model runtime has loaded successfully."""

    ready = False
    model_id = "dinov2-vit-s-14-int8-onnx"
    # The MODEL version, mirroring model_manifest.json for the window before
    # the runtime has loaded it. It is not the App version in config.yaml and
    # settings.py, which happens to read the same today: this number identifies
    # the embeddings every stored Baseline Bucket and Framing Epoch is keyed
    # to, so an App release must leave it exactly where it is.
    model_version = "1.0.0"
    embedding_dimension = 384

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        """Refuse inference, which the HTTP layer never reaches while unready."""

        raise RuntimeError("model is unavailable")


async def analyze_frame(
    *,
    request_id: str,
    metadata: AnalyzeMetadata,
    image_body: bytes,
    analyzer: Analyzer,
) -> dict[str, Any]:
    """Decode one frame, apply the absolute floor, and infer only if it passes.

    Inference is the expensive half and a rejected frame never reaches it: an
    absolute floor exists precisely so a black frame costs no model. Decoding and
    measurement are pixel-bound work and run off the event loop so the App's single
    inference slot and its deadline stay honest.
    """

    image = await asyncio.to_thread(decode_image, image_body)
    signals = await asyncio.to_thread(measure_quality_signals, image)
    reasons = frame_quality_reasons(signals, metadata.light_state)
    if reasons:
        return build_rejected_response(
            request_id=request_id, signals=signals, reasons=reasons
        )
    embedding = await analyzer.embed(image)
    if len(embedding) != analyzer.embedding_dimension:
        raise RuntimeError("analyzer returned an unexpected embedding dimension")
    return build_analyzed_response(
        request_id=request_id,
        model_id=analyzer.model_id,
        model_version=analyzer.model_version,
        embedding=embedding,
        signals=signals,
    )


class InferenceSlot:
    """A process-local, non-queueing admission boundary for one inference."""

    def __init__(self) -> None:
        self._guard = Lock()
        self._occupied = False

    def try_acquire(self) -> bool:
        """Occupy the slot immediately or report that it is busy."""

        with self._guard:
            if self._occupied:
                return False
            self._occupied = True
            return True

    def release(self) -> None:
        """Make the slot available after its admitted operation finishes."""

        with self._guard:
            self._occupied = False
