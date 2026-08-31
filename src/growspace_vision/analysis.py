"""Boundary between HTTP orchestration and model inference."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    """Raw HTTP payload awaiting the contract parser added by the endpoint ticket."""

    body: bytes
    content_type: str


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

    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        """Analyze one request after HTTP orchestration admits it."""


class UnavailableAnalyzer:
    """Startup state used until a model runtime has loaded successfully."""

    ready = False
    model_id = "dinov2-vit-s-14-int8-onnx"
    model_version = "1.0.0"
    embedding_dimension = 384

    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        raise RuntimeError("model is unavailable")


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
