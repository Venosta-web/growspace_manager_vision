"""Black-box HTTP behavior for the Growspace Vision service."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from growspace_vision import ServiceSettings, create_app
from growspace_vision.__main__ import application
from growspace_vision.analysis import AnalysisInput

FIXTURES = Path(__file__).parents[1] / "contracts/growspace-vision/v1/fixtures/valid"


def load_fixture(name: str) -> dict[str, object]:
    """Load an independently maintained normative contract fixture."""

    return cast(
        dict[str, object],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


class ReadyAnalyzer:
    """Test implementation of the future model-runtime boundary."""

    ready = True
    model_id = "dinov2-vit-s-14-int8-onnx"
    model_version = "1.0.0"
    embedding_dimension = 384

    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        return load_fixture("analyze-response-analyzed.json")


class NeverCompletesAnalyzer(ReadyAnalyzer):
    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class BlockingAnalyzer(ReadyAnalyzer):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        self.started.set()
        await self.release.wait()
        return load_fixture("analyze-response-analyzed.json")


class FailingAnalyzer(ReadyAnalyzer):
    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        raise RuntimeError("test-secret /private/model.onnx")


class BrokenReadinessAnalyzer:
    model_id = "dinov2-vit-s-14-int8-onnx"
    model_version = "1.0.0"
    embedding_dimension = 384

    @property
    def ready(self) -> bool:
        raise RuntimeError("test-secret /private/model.onnx")

    async def analyze(self, request: AnalysisInput) -> dict[str, object]:
        return load_fixture("analyze-response-analyzed.json")


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
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=ReadyAnalyzer(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"schema_version": 1, "status": "ready"},
        )

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
        response = await self.client.get(
            "/info",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), load_fixture("info.json"))

    async def test_models_matches_the_normative_contract_fixture(self) -> None:
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=ReadyAnalyzer(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
            headers={"Authorization": "Bearer test-secret"},
        ) as client:
            response = await client.get("/models?schema_version=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), load_fixture("models.json"))

    async def test_models_rejects_an_unsupported_schema_version(self) -> None:
        response = await self.client.get(
            "/models?schema_version=2",
            headers={"Authorization": "Bearer test-secret"},
        )

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
        response = await self.client.get(
            "/models",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            {
                "code": "invalid_request",
                "message": "schema_version is required",
            },
        )

    async def test_analysis_deadline_returns_a_closed_internal_failure(self) -> None:
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=NeverCompletesAnalyzer(),
            inference_timeout_seconds=0.01,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
            response = await client.post(
                "/analyze",
                content=b"not-yet-decoded",
                headers={
                    "Authorization": "Bearer test-secret",
                    "Content-Type": "application/octet-stream",
                },
            )

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

    async def test_concurrent_analysis_is_rejected_instead_of_queued(self) -> None:
        analyzer = BlockingAnalyzer()
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=analyzer,
        )
        headers = {
            "Authorization": "Bearer test-secret",
            "Content-Type": "application/octet-stream",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
            first_request = asyncio.create_task(
                client.post("/analyze", content=b"first", headers=headers)
            )
            await asyncio.wait_for(analyzer.started.wait(), timeout=1)

            concurrent_response = await client.post(
                "/analyze", content=b"second", headers=headers
            )

            analyzer.release.set()
            first_response = await first_request

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(concurrent_response.status_code, 429)
        self.assertEqual(concurrent_response.headers["Retry-After"], "1")
        self.assertEqual(
            concurrent_response.json()["error"],
            {"code": "busy", "message": "Analysis is already in progress"},
        )

    async def test_internal_analysis_failure_does_not_leak_details(self) -> None:
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=FailingAnalyzer(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
            response = await client.post(
                "/analyze",
                content=b"not-yet-decoded",
                headers={
                    "Authorization": "Bearer test-secret",
                    "Content-Type": "application/octet-stream",
                },
            )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(
            body["error"],
            {"code": "internal_failure", "message": "Analysis failed"},
        )
        self.assertNotIn("test-secret", response.text)
        self.assertNotIn("/private/model.onnx", response.text)

    async def test_unknown_route_uses_the_closed_error_shape(self) -> None:
        response = await self.client.get(
            "/unknown",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"],
            {"code": "invalid_request", "message": "Route not found"},
        )

    async def test_unhandled_service_failure_uses_the_closed_error_shape(self) -> None:
        app = create_app(
            ServiceSettings(bearer_token="test-secret"),
            analyzer=BrokenReadinessAnalyzer(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://vision.test",
        ) as client:
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
                "UNRELATED_SECRET": "must-not-be-read",
            },
            clear=True,
        ):
            settings = ServiceSettings.from_env()

        self.assertEqual(settings.bearer_token, "configured-secret")
        self.assertEqual(settings.service_version, "1.2.3")

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
