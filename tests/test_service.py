"""Black-box HTTP behavior for the Growspace Vision service."""

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncByteStream, AsyncClient
from support import (
    BEARER,
    EMBEDDING_DIMENSION,
    MODEL_ID,
    MODEL_VERSION,
    ReadyAnalyzer,
    analyze_request,
    assert_matches_contract_response,
    load_contract_fixture,
    load_fixture,
    metadata_json,
    usable_frame,
)

from growspace_vision import ServiceSettings, create_app
from growspace_vision.__main__ import application
from growspace_vision.images import DecodedImage


class NeverCompletesAnalyzer(ReadyAnalyzer):
    async def embed(self, image: DecodedImage) -> Sequence[float]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class DeadlineCrossingBody(AsyncByteStream):
    """Make the deadline expire as middleware finishes a synchronous body read."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        # Deliberately hold the loop past the deadline: the receive task group's
        # own cancellation and the overdue timer then run at the same checkpoint.
        time.sleep(0.2)  # noqa: ASYNC251
        yield self.body


class BlockingAnalyzer(ReadyAnalyzer):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        self.started.set()
        await self.release.wait()
        return [0.0] * EMBEDDING_DIMENSION


class FailingAnalyzer(ReadyAnalyzer):
    async def embed(self, image: DecodedImage) -> Sequence[float]:
        raise RuntimeError("test-secret /private/model.onnx")


class WrongDimensionAnalyzer(ReadyAnalyzer):
    async def embed(self, image: DecodedImage) -> Sequence[float]:
        return [0.0] * (EMBEDDING_DIMENSION - 1)


class BrokenReadinessAnalyzer:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    embedding_dimension = EMBEDDING_DIMENSION

    @property
    def ready(self) -> bool:
        raise RuntimeError("test-secret /private/model.onnx")

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        raise AssertionError("unreachable")


class GrowspaceVisionServiceTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the service only through its public ASGI interface."""

    async def asyncSetUp(self) -> None:
        app = create_app(ServiceSettings(bearer_token="test-secret"))
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    def client_for(self, analyzer: Any, **options: Any) -> AsyncClient:
        """Build a client over a service whose model runtime is under test."""

        return AsyncClient(
            transport=ASGITransport(
                app=create_app(
                    ServiceSettings(bearer_token="test-secret"),
                    analyzer=analyzer,
                    **options,
                )
            ),
            base_url="http://vision.test",
            headers=BEARER,
        )

    async def test_health_reports_unavailable_model_without_authentication(
        self,
    ) -> None:
        response = await self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "schema_version": 1,
                "error": {
                    "code": "model_not_loaded",
                    "message": "Model is not loaded",
                },
            },
        )

    async def test_health_reports_ready_model_without_authentication(self) -> None:
        async with self.client_for(ReadyAnalyzer()) as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), load_fixture("health-ready.json"))

    async def test_info_rejects_a_missing_bearer_token_with_closed_error(self) -> None:
        response = await self.client.get("/info")

        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(
            body["error"],
            {"code": "unauthorized", "message": "Authentication required"},
        )
        self.assertEqual(set(body), {"schema_version", "request_id", "error"})

    async def test_info_matches_the_normative_contract_fixture(self) -> None:
        response = await self.client.get("/info", headers=BEARER)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), load_fixture("info.json"))

    async def test_models_matches_the_normative_contract_fixture(self) -> None:
        async with self.client_for(ReadyAnalyzer()) as client:
            response = await client.get("/models?schema_version=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), load_fixture("models.json"))

    async def test_models_rejects_an_unsupported_schema_version(self) -> None:
        response = await self.client.get("/models?schema_version=2", headers=BEARER)

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(
            body["error"],
            {
                "code": "unsupported_schema_version",
                "message": "Schema version is unsupported",
            },
        )
        self.assertEqual(set(body), {"schema_version", "request_id", "error"})

    async def test_models_rejects_a_missing_schema_version(self) -> None:
        response = await self.client.get("/models", headers=BEARER)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "schema_version is required",
            },
        )

    async def test_analysis_is_refused_while_no_model_is_loaded(self) -> None:
        response = await self.client.post(
            "/analyze", headers=BEARER, **analyze_request(usable_frame())
        )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        expected = load_fixture("error-model-not-loaded.json")
        expected["request_id"] = body["request_id"]
        self.assertEqual(body, expected)

    async def test_analysis_requires_bearer_authentication(self) -> None:
        response = await self.client.post("/analyze", **analyze_request(usable_frame()))

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"],
            {"code": "unauthorized", "message": "Authentication required"},
        )

    async def test_analysis_rejects_every_negative_metadata_fixture(self) -> None:
        manifest = load_contract_fixture("manifest.json")
        fixtures = [
            entry
            for entry in manifest["invalid"]
            if entry["schema"] == "AnalyzeMetadata"
        ]

        async with self.client_for(ReadyAnalyzer()) as client:
            for fixture in fixtures:
                with self.subTest(fixture=fixture["file"]):
                    metadata = load_contract_fixture(fixture["file"])
                    response = await client.post(
                        "/analyze",
                        **analyze_request(
                            usable_frame(), metadata=json.dumps(metadata)
                        ),
                    )

                    assert_matches_contract_response(response, "/analyze", "post")
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(
                        response.json()["error"]["code"], "invalid_request"
                    )

    async def test_analysis_rejects_an_unknown_model_identity(self) -> None:
        async with self.client_for(ReadyAnalyzer()) as client:
            response = await client.post(
                "/analyze",
                **analyze_request(
                    usable_frame(), metadata=metadata_json(model_version="2.0.0")
                ),
            )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "Requested model is unknown",
            },
        )

    async def test_analysis_rejects_an_unknown_model_while_unavailable(self) -> None:
        response = await self.client.post(
            "/analyze",
            headers=BEARER,
            **analyze_request(
                usable_frame(), metadata=metadata_json(model_version="2.0.0")
            ),
        )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_analysis_requires_a_multipart_body(self) -> None:
        async with self.client_for(ReadyAnalyzer()) as client:
            response = await client.post(
                "/analyze",
                content=b"not-a-multipart-body",
                headers={"Content-Type": "application/octet-stream"},
            )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "Request must be multipart/form-data",
            },
        )

    async def test_analysis_requires_exactly_the_metadata_and_image_parts(
        self,
    ) -> None:
        bodies: list[dict[str, Any]] = [
            {"data": {"metadata": metadata_json()}},
            {"files": {"image": ("frame.png", usable_frame(), "image/png")}},
            {
                "data": {"metadata": metadata_json(), "notes": "extra"},
                "files": {"image": ("frame.png", usable_frame(), "image/png")},
            },
        ]
        async with self.client_for(ReadyAnalyzer()) as client:
            for body in bodies:
                with self.subTest(parts=sorted(body)):
                    response = await client.post("/analyze", **body)

                    assert_matches_contract_response(response, "/analyze", "post")
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(
                        response.json()["error"]["code"], "invalid_request"
                    )

    async def test_analysis_rejects_a_future_analysis_schema(self) -> None:
        async with self.client_for(ReadyAnalyzer()) as client:
            response = await client.post(
                "/analyze",
                **analyze_request(
                    usable_frame(), metadata=metadata_json(schema_version=2)
                ),
            )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "unsupported_schema_version",
                "message": "Schema version is unsupported",
            },
        )

    async def test_analysis_deadline_returns_a_closed_internal_failure(self) -> None:
        async with self.client_for(
            NeverCompletesAnalyzer(), inference_timeout_seconds=0.01
        ) as client:
            response = await asyncio.wait_for(
                client.post("/analyze", **analyze_request(usable_frame())), timeout=2
            )

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(
            body["error"],
            {
                "code": "internal_failure",
                "message": "Analysis deadline exceeded",
            },
        )
        self.assertEqual(set(body), {"schema_version", "request_id", "error"})

    async def test_deadline_during_body_read_stops_analysis_and_releases_slot(
        self,
    ) -> None:
        analyzer = BlockingAnalyzer()
        async with self.client_for(analyzer, inference_timeout_seconds=0.1) as client:
            request = client.build_request(
                "POST", "/analyze", **analyze_request(usable_frame())
            )
            request.stream = DeadlineCrossingBody(request.read())
            # Bound the regression itself even if the service loses cancellation.
            response = await asyncio.wait_for(client.send(request), timeout=2)

            assert_matches_contract_response(response, "/analyze", "post")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(
                response.json()["error"],
                {
                    "code": "internal_failure",
                    "message": "Analysis deadline exceeded",
                },
            )
            self.assertFalse(analyzer.started.is_set())

            analyzer.release.set()
            recovered = await asyncio.wait_for(
                client.post("/analyze", **analyze_request(usable_frame())), timeout=2
            )

        self.assertEqual(recovered.status_code, 200)
        assert_matches_contract_response(recovered, "/analyze", "post")

    async def test_concurrent_analysis_is_rejected_instead_of_queued(self) -> None:
        analyzer = BlockingAnalyzer()
        async with self.client_for(analyzer) as client:
            first_request = asyncio.create_task(
                client.post("/analyze", **analyze_request(usable_frame()))
            )
            await asyncio.wait_for(analyzer.started.wait(), timeout=5)

            concurrent_response = await client.post(
                "/analyze", **analyze_request(usable_frame())
            )

            analyzer.release.set()
            first_response = await first_request

        assert_matches_contract_response(first_response, "/analyze", "post")
        assert_matches_contract_response(concurrent_response, "/analyze", "post")
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(concurrent_response.status_code, 429)
        self.assertEqual(concurrent_response.headers["Retry-After"], "1")
        self.assertEqual(
            concurrent_response.json()["error"],
            {"code": "busy", "message": "Analysis is already in progress"},
        )

    async def test_internal_analysis_failure_does_not_leak_details(self) -> None:
        async with self.client_for(FailingAnalyzer()) as client:
            response = await client.post("/analyze", **analyze_request(usable_frame()))

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(
            body["error"],
            {"code": "internal_failure", "message": "Analysis failed"},
        )
        self.assertNotIn("test-secret", response.text)
        self.assertNotIn("/private/model.onnx", response.text)

    async def test_analysis_refuses_an_embedding_with_the_wrong_dimension(self) -> None:
        async with self.client_for(WrongDimensionAnalyzer()) as client:
            response = await client.post("/analyze", **analyze_request(usable_frame()))

        assert_matches_contract_response(response, "/analyze", "post")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["error"],
            {"code": "internal_failure", "message": "Analysis failed"},
        )

    async def test_unknown_route_uses_the_closed_error_shape(self) -> None:
        response = await self.client.get("/unknown", headers=BEARER)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"],
            {"code": "invalid_request", "message": "Route not found"},
        )

    async def test_unhandled_service_failure_uses_the_closed_error_shape(self) -> None:
        async with self.client_for(BrokenReadinessAnalyzer()) as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["error"],
            {"code": "internal_failure", "message": "Service request failed"},
        )
        self.assertNotIn("test-secret", response.text)
        self.assertNotIn("/private/model.onnx", response.text)

    def test_process_configuration_loads_only_the_service_inputs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GROWSPACE_VISION_TOKEN": "configured-secret",
                "GROWSPACE_VISION_SERVICE_VERSION": "1.2.3",
                "GROWSPACE_VISION_MODEL_PATH": "/models/model_int8.onnx",
                "UNRELATED_SECRET": "must-not-be-read",
            },
            clear=True,
        ):
            settings = ServiceSettings.from_env()

        self.assertEqual(settings.bearer_token, "configured-secret")
        self.assertEqual(settings.service_version, "1.2.3")
        self.assertEqual(settings.model_path, Path("/models/model_int8.onnx"))

    def test_process_configuration_does_not_render_the_bearer_token(self) -> None:
        settings = ServiceSettings(bearer_token="test-secret")

        self.assertNotIn("test-secret", repr(settings))

    def test_process_configuration_rejects_an_oversized_service_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "service_version is too long"):
            ServiceSettings(
                bearer_token="test-secret",
                service_version="v" * 129,
            )

    async def test_process_factory_constructs_the_service_from_environment(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"GROWSPACE_VISION_TOKEN": "configured-secret"},
            clear=True,
        ):
            app = application()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "model_not_loaded")


@unittest.skipUnless(
    os.environ.get("GROWSPACE_VISION_TEST_MODEL_PATH"),
    "the verified production artifact was not supplied locally",
)
class ProductionArtifactServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_startup_serves_one_real_vision_analysis(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GROWSPACE_VISION_TOKEN": "test-secret",
                "GROWSPACE_VISION_MODEL_PATH": os.environ[
                    "GROWSPACE_VISION_TEST_MODEL_PATH"
                ],
            },
            clear=True,
        ):
            app = application()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
            headers=BEARER,
        ) as client:
            health = await client.get("/health")
            models = await client.get("/models?schema_version=1")
            analysis = await client.post("/analyze", **analyze_request(usable_frame()))

        assert_matches_contract_response(analysis, "/analyze", "post")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(models.json()["models"][0]["state"], "loaded")
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(analysis.json()["status"], "analyzed")
        self.assertEqual(analysis.json()["embedding"]["dimension"], 384)


if __name__ == "__main__":
    unittest.main()
