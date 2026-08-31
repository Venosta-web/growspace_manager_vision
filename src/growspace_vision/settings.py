"""Process configuration for Growspace Vision."""

import os
from dataclasses import dataclass, field
from typing import Self


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """Validated settings needed to construct the service."""

    bearer_token: str = field(repr=False)
    service_version: str = "1.0.0"

    @classmethod
    def from_env(cls) -> Self:
        """Load the deliberately small environment configuration surface."""

        token = os.environ.get("GROWSPACE_VISION_TOKEN")
        if token is None:
            raise ValueError("GROWSPACE_VISION_TOKEN is required")
        return cls(
            bearer_token=token,
            service_version=os.environ.get("GROWSPACE_VISION_SERVICE_VERSION", "1.0.0"),
        )

    def __post_init__(self) -> None:
        if not self.bearer_token:
            raise ValueError("bearer_token must not be empty")
        if not self.service_version:
            raise ValueError("service_version must not be empty")
        if len(self.service_version) > 128:
            raise ValueError("service_version is too long")
