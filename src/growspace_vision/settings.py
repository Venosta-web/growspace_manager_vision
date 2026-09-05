"""Process configuration for Growspace Vision."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

# The App version, and the only place the service spells it. `config.yaml` is
# the source of truth — the App store reads the version there and pulls exactly
# that GHCR tag — and the image passes it in through
# GROWSPACE_VISION_SERVICE_VERSION; this is what a run outside the image falls
# back to. `tests/test_app_packaging.py` fails a bump that moves one and not
# the other.
#
# This is NOT the model version. That is `model_manifest.json` and
# `analysis.py`, it identifies the embeddings a user's Baseline Buckets are
# keyed to, and it must not move when the App version does.
DEFAULT_SERVICE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """Validated settings needed to construct the service."""

    bearer_token: str = field(repr=False)
    service_version: str = DEFAULT_SERVICE_VERSION
    model_path: Path = Path("/opt/growspace-vision/models/model_int8.onnx")

    @classmethod
    def from_env(cls) -> Self:
        """Load the deliberately small environment configuration surface."""

        token = os.environ.get("GROWSPACE_VISION_TOKEN")
        if token is None:
            raise ValueError("GROWSPACE_VISION_TOKEN is required")
        return cls(
            bearer_token=token,
            service_version=os.environ.get(
                "GROWSPACE_VISION_SERVICE_VERSION", DEFAULT_SERVICE_VERSION
            ),
            model_path=Path(
                os.environ.get(
                    "GROWSPACE_VISION_MODEL_PATH",
                    "/opt/growspace-vision/models/model_int8.onnx",
                )
            ),
        )

    def __post_init__(self) -> None:
        if not self.bearer_token:
            raise ValueError("bearer_token must not be empty")
        if not self.service_version:
            raise ValueError("service_version must not be empty")
        if len(self.service_version) > 128:
            raise ValueError("service_version is too long")
