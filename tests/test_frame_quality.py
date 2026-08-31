"""The absolute Frame Quality floor, exercised through the service's HTTP boundary.

The thresholds asserted here are ADR 0005's, measured in
`docs/research/2026-08-31-frame-quality-gate.md`. Every frame below is built so its
signals land exactly on or beside a threshold rather than near it, which is what
makes the inclusive and exclusive side of each comparison testable at all.
"""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any

import numpy as np
from httpx import ASGITransport, AsyncClient, Response
from PIL import Image
from support import (
    BEARER,
    REMOVED,
    ReadyAnalyzer,
    analyze_request,
    assert_matches_analyze_response,
    clipped_frame,
    encode,
    load_fixture,
    metadata_json,
    striped_frame,
    uniform_frame,
    usable_frame,
)

from growspace_vision import ServiceSettings, create_app
from growspace_vision.application import MAX_REQUEST_BYTES
from growspace_vision.images import (
    MAX_IMAGE_BYTES,
    ImageTooLarge,
    UndecodableImage,
    UnsupportedImageFormat,
    decode_image,
)
from growspace_vision.quality import (
    QualitySignals,
    frame_quality_reasons,
    measure_quality_signals,
)


class FrameQualityFloorTest(unittest.IsolatedAsyncioTestCase):
    """Drive the gate the way Home Assistant does: one multipart request at a time."""

    async def asyncSetUp(self) -> None:
        self.analyzer = ReadyAnalyzer()
        self.client = AsyncClient(
            transport=ASGITransport(
                app=create_app(
                    ServiceSettings(bearer_token="test-secret"),
                    analyzer=self.analyzer,
                )
            ),
            base_url="http://vision.test",
            headers=BEARER,
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def analyze(self, image: bytes, **options: Any) -> Response:
        """Post one Vision Analysis, holding every 200 to the normative schema."""

        response = await self.client.post(
            "/analyze", **analyze_request(image, **options)
        )
        if response.status_code == 200:
            assert_matches_analyze_response(response.json())
        return response

    async def accepted(self, image: bytes, **options: Any) -> dict[str, Any]:
        response = await self.analyze(image, **options)
        self.assertEqual(response.status_code, 200)
        body: dict[str, Any] = response.json()
        self.assertEqual(body["status"], "analyzed")
        self.assertEqual(body["quality"]["reasons"], [])
        return body

    async def rejected(
        self, image: bytes, reasons: list[str], **options: Any
    ) -> dict[str, Any]:
        response = await self.analyze(image, **options)
        self.assertEqual(response.status_code, 200)
        body: dict[str, Any] = response.json()
        self.assertEqual(body["status"], "rejected")
        self.assertEqual(body["quality"]["reasons"], reasons)
        return body

    async def test_a_usable_lit_frame_is_analyzed(self) -> None:
        body = await self.accepted(usable_frame())

        self.assertEqual(body["model"]["model_id"], self.analyzer.model_id)
        self.assertEqual(body["model"]["model_version"], self.analyzer.model_version)
        self.assertEqual(body["embedding"]["dimension"], 384)
        self.assertEqual(len(body["embedding"]["values"]), 384)
        self.assertEqual(body["regions"], [])

    async def test_every_analyzed_frame_reports_its_three_signals(self) -> None:
        signals = (await self.accepted(striped_frame(120, 160)))["quality"]["signals"]

        self.assertEqual(signals["mean_luminance"], 140.0)
        self.assertEqual(signals["clipped_pixel_fraction"], 0.0)
        self.assertAlmostEqual(signals["mean_absolute_gradient"], 20.0, places=5)

    async def test_darkness_floor_rejects_below_sixteen_and_admits_sixteen(
        self,
    ) -> None:
        dark = await self.rejected(
            striped_frame(13, 17), ["too_dark"], light_state="unknown"
        )
        lit = await self.accepted(striped_frame(14, 18), light_state="unknown")

        self.assertEqual(dark["quality"]["signals"]["mean_luminance"], 15.0)
        self.assertEqual(lit["quality"]["signals"]["mean_luminance"], 16.0)

    async def test_detail_floor_rejects_below_half_and_admits_half(self) -> None:
        blank = await self.rejected(uniform_frame(100), ["low_detail"])
        textured = await self.accepted(striped_frame(100, 101))

        self.assertEqual(blank["quality"]["signals"]["mean_absolute_gradient"], 0.0)
        self.assertEqual(textured["quality"]["signals"]["mean_absolute_gradient"], 0.5)

    async def test_clipping_ceiling_rejects_at_ninety_percent_and_admits_below(
        self,
    ) -> None:
        blown = await self.rejected(clipped_frame(90), ["overexposed"])
        bright = await self.accepted(clipped_frame(89))

        self.assertEqual(blown["quality"]["signals"]["clipped_pixel_fraction"], 0.9)
        self.assertEqual(bright["quality"]["signals"]["clipped_pixel_fraction"], 0.89)

    async def test_ordinary_blown_highlights_are_not_a_rejection(self) -> None:
        """76 of 96 lit corpus frames blow more than 5% of their pixels."""

        bright = await self.accepted(clipped_frame(18))

        self.assertEqual(bright["quality"]["signals"]["clipped_pixel_fraction"], 0.18)

    async def test_a_frame_reports_every_floor_it_fails(self) -> None:
        body = await self.rejected(
            uniform_frame(0),
            ["too_dark", "low_detail", "light_state_mismatch"],
            light_state="on",
        )

        self.assertEqual(body["quality"]["signals"]["mean_luminance"], 0.0)
        self.assertEqual(body["quality"]["signals"]["mean_absolute_gradient"], 0.0)

    async def test_a_dark_frame_under_a_light_believed_on_also_mismatches(
        self,
    ) -> None:
        await self.rejected(
            striped_frame(13, 17),
            ["too_dark", "light_state_mismatch"],
            light_state="on",
        )

    async def test_an_unlit_capture_mismatches_however_good_the_frame(self) -> None:
        await self.rejected(usable_frame(), ["light_state_mismatch"], light_state="off")

    async def test_an_unknown_light_state_never_mismatches(self) -> None:
        await self.rejected(striped_frame(13, 17), ["too_dark"], light_state="unknown")
        await self.accepted(usable_frame(), light_state="unknown")

    async def test_a_rejected_frame_carries_no_embedding_and_costs_no_inference(
        self,
    ) -> None:
        body = await self.rejected(
            uniform_frame(0), ["too_dark", "low_detail", "light_state_mismatch"]
        )

        self.assertNotIn("embedding", body)
        self.assertNotIn("model", body)
        self.assertEqual(self.analyzer.embedded, [])

    async def test_jpeg_and_png_are_both_accepted(self) -> None:
        column = np.where(np.arange(64) % 2 == 0, 120, 160).astype(np.uint8)
        pixels = np.repeat(np.tile(column, (64, 1))[:, :, None], 3, axis=2)

        for image_format, media_type in (("JPEG", "image/jpeg"), ("PNG", "image/png")):
            with self.subTest(image_format=image_format):
                await self.accepted(
                    encode(pixels, image_format),
                    filename=f"frame.{image_format.lower()}",
                    content_type=media_type,
                )

    async def test_a_format_that_is_neither_jpeg_nor_png_is_refused(self) -> None:
        response = await self.analyze(
            encode(np.zeros((8, 8, 3), dtype=np.uint8), "GIF"),
            filename="frame.gif",
            content_type="image/gif",
        )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "unsupported_image_format",
                "message": "Image must be JPEG or PNG",
            },
        )

    async def test_a_body_that_is_not_an_image_is_refused_as_a_format(self) -> None:
        response = await self.analyze(b"this is not an image")

        self.assertEqual(response.status_code, 415)

    async def test_a_truncated_image_is_an_invalid_body_rather_than_a_format(
        self,
    ) -> None:
        response = await self.analyze(usable_frame()[:64])

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {"code": "invalid_request", "message": "Image could not be decoded"},
        )

    async def test_an_image_over_ten_mebibytes_is_refused(self) -> None:
        response = await self.analyze(b"\x00" * (MAX_IMAGE_BYTES + 1))

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()["error"],
            {"code": "image_too_large", "message": "Image exceeds the service limits"},
        )

    async def test_an_oversized_declared_body_is_refused_before_it_is_read(
        self,
    ) -> None:
        response = await self.client.post(
            "/analyze",
            content=b"\x00" * (MAX_REQUEST_BYTES + 1),
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "image_too_large")

    async def test_a_body_without_a_declared_length_is_refused(self) -> None:
        async def stream() -> AsyncIterator[bytes]:
            yield b"\x00" * 16

        response = await self.client.post(
            "/analyze",
            content=stream(),
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "Request must declare its Content-Length",
            },
        )

    async def test_the_light_state_is_the_only_observation_the_gate_reads(
        self,
    ) -> None:
        response = await self.analyze(usable_frame(), metadata=metadata_json(vpd=1.2))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_an_unknown_light_state_value_is_refused(self) -> None:
        response = await self.analyze(usable_frame(), light_state="dim")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_metadata_must_carry_every_contract_field(self) -> None:
        response = await self.analyze(
            usable_frame(), metadata=metadata_json(camera_id=REMOVED)
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "Metadata is missing required fields",
            },
        )


class NormativeRejectionFixtureTest(unittest.TestCase):
    """The published rejection fixture must be what this floor actually produces."""

    def test_the_rejected_fixture_signals_produce_its_own_reasons(self) -> None:
        fixture = load_fixture("analyze-response-rejected.json")
        signals = QualitySignals(**fixture["quality"]["signals"])

        reasons = frame_quality_reasons(signals, "on")

        self.assertEqual(list(reasons), fixture["quality"]["reasons"])


class ImageDecodingLimitTest(unittest.TestCase):
    """Decoding limits that are cheaper to prove directly than through HTTP."""

    def test_the_decoded_pixel_ceiling_admits_exactly_twenty_four_megapixels(
        self,
    ) -> None:
        self.assertEqual(decode_image(_solid_png(6000, 4000)).width, 6000)
        with self.assertRaises(ImageTooLarge):
            decode_image(_solid_png(6000, 4001))

    def test_an_oversized_encoded_body_is_refused_before_decoding(self) -> None:
        with self.assertRaises(ImageTooLarge):
            decode_image(b"\x00" * (MAX_IMAGE_BYTES + 1))

    def test_an_empty_body_is_undecodable_rather_than_unsupported(self) -> None:
        with self.assertRaises(UndecodableImage):
            decode_image(b"")

    def test_an_unidentifiable_body_is_an_unsupported_format(self) -> None:
        with self.assertRaises(UnsupportedImageFormat):
            decode_image(b"not an image at all")

    def test_a_decoded_image_keeps_its_full_resolution_rgb_pixels(self) -> None:
        image = decode_image(uniform_frame(100, size=8))

        self.assertEqual(image.pixels.shape, (8, 8, 3))
        self.assertEqual(image.pixels.dtype, np.uint8)
        self.assertEqual((image.width, image.height), (8, 8))

    def test_a_palette_png_is_decoded_as_rgb(self) -> None:
        buffer = BytesIO()
        Image.new("P", (8, 8), color=3).save(buffer, format="PNG")

        self.assertEqual(decode_image(buffer.getvalue()).pixels.shape, (8, 8, 3))

    def test_a_single_pixel_frame_has_no_gradient_rather_than_no_number(self) -> None:
        signals = measure_quality_signals(decode_image(uniform_frame(200, size=1)))

        self.assertEqual(signals.mean_absolute_gradient, 0.0)
        self.assertEqual(signals.mean_luminance, 200.0)


def _solid_png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
