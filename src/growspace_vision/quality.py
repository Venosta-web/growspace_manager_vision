"""The absolute layer of the Frame Quality Gate, decidable from one image.

Growspace Vision holds no history, so it applies only the rejections that need
none. Everything relative to a camera's own past — the exposure and detail rails —
belongs to Home Assistant's Quality History and is deliberately absent here.

The thresholds are service behaviour rather than wire shape: they move with
`service_version`, never with `schema_version`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from growspace_vision.images import DecodedImage
from growspace_vision.metadata import LightState

DARKNESS_FLOOR: Final = 16.0
DETAIL_FLOOR: Final = 0.5
CLIPPING_CEILING: Final = 0.90
CLIPPED_LUMINANCE: Final = 245.0

_BT601_WEIGHTS: Final = (0.299, 0.587, 0.114)


@dataclass(frozen=True, slots=True)
class QualitySignals:
    """The three non-plant measurements the V1 contract defines over decoded pixels."""

    mean_luminance: float
    clipped_pixel_fraction: float
    mean_absolute_gradient: float

    def as_contract(self) -> dict[str, float]:
        """Render the signals in their normative wire order."""

        return {
            "mean_luminance": self.mean_luminance,
            "clipped_pixel_fraction": self.clipped_pixel_fraction,
            "mean_absolute_gradient": self.mean_absolute_gradient,
        }


def measure_quality_signals(image: DecodedImage) -> QualitySignals:
    """Measure one decoded frame exactly as the contract's prose specifies."""

    channels = image.pixels.astype(np.float32)
    red, green, blue = _BT601_WEIGHTS
    luminance = (
        red * channels[..., 0] + green * channels[..., 1] + blue * channels[..., 2]
    )
    return QualitySignals(
        mean_luminance=float(luminance.mean()),
        clipped_pixel_fraction=float((luminance > CLIPPED_LUMINANCE).mean()),
        mean_absolute_gradient=_mean_absolute_gradient(luminance),
    )


def frame_quality_reasons(
    signals: QualitySignals, light_state: LightState
) -> tuple[str, ...]:
    """Return every floor a frame fails, in the contract's QualityReason order.

    A frame fails as many floors as it fails; the reasons are reported together
    because a dark frame captured under a light the schedule believes is on says
    something neither signal says alone.
    """

    too_dark = signals.mean_luminance < DARKNESS_FLOOR
    reasons: list[str] = []
    if too_dark:
        reasons.append("too_dark")
    if signals.clipped_pixel_fraction >= CLIPPING_CEILING:
        reasons.append("overexposed")
    if signals.mean_absolute_gradient < DETAIL_FLOOR:
        reasons.append("low_detail")
    if _light_state_disagrees(light_state, too_dark=too_dark):
        reasons.append("light_state_mismatch")
    return tuple(reasons)


def _light_state_disagrees(light_state: LightState, *, too_dark: bool) -> bool:
    """Compare the reported light cycle with the frame rather than ranking them.

    V1 scores only lit captures, so `off` always disagrees with a capture that was
    taken at all. `unknown` can never disagree, and leaves the image floor alone.
    """

    if light_state == "off":
        return True
    return light_state == "on" and too_dark


def _mean_absolute_gradient(luminance: NDArray[np.float32]) -> float:
    """Average the mean absolute first differences along both image axes."""

    horizontal = _mean_absolute_difference(luminance, axis=1)
    vertical = _mean_absolute_difference(luminance, axis=0)
    return (horizontal + vertical) / 2.0


def _mean_absolute_difference(luminance: NDArray[np.float32], *, axis: int) -> float:
    """Return 0 where an axis is one pixel wide and therefore has no differences."""

    if luminance.shape[axis] < 2:
        return 0.0
    return float(np.abs(np.diff(luminance, axis=axis)).mean())
