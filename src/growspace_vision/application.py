"""ASGI application for Growspace Vision."""

import asyncio
from collections.abc import Awaitable, Callable
from secrets import compare_digest
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from growspace_vision.analysis import (
    AnalysisInput,
    Analyzer,
    InferenceSlot,
    UnavailableAnalyzer,
)
from growspace_vision.contract import build_info_response, build_models_response
from growspace_vision.responses import error_response
from growspace_vision.settings import ServiceSettings


def create_app(
    settings: ServiceSettings,
    *,
    analyzer: Analyzer | None = None,
    inference_timeout_seconds: float = 10.0,
) -> FastAPI:
    """Create an isolated service application from explicit settings."""

    active_analyzer = analyzer or UnavailableAnalyzer()
    inference_slot = InferenceSlot()
    if inference_timeout_seconds <= 0:
        raise ValueError("inference_timeout_seconds must be positive")
    app = FastAPI(
        title="Growspace Vision API",
        version=settings.service_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(StarletteHTTPException)
    async def closed_http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        message = {
            404: "Route not found",
            405: "Method not allowed",
        }.get(error.status_code, "Invalid request")
        return error_response(
            status_code=error.status_code,
            request_id=request.state.request_id,
            code="invalid_request",
            message=message,
        )

    @app.middleware("http")
    async def authenticate(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = str(uuid4())
        if request.url.path != "/health":
            scheme, _, supplied_token = request.headers.get(
                "authorization", ""
            ).partition(" ")
            authenticated = (
                scheme.lower() == "bearer"
                and bool(supplied_token)
                and compare_digest(supplied_token, settings.bearer_token)
            )
            if not authenticated:
                return error_response(
                    status_code=401,
                    request_id=request.state.request_id,
                    code="unauthorized",
                    message="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        try:
            return await call_next(request)
        except Exception:
            return error_response(
                status_code=500,
                request_id=request.state.request_id,
                code="internal_failure",
                message="Service request failed",
            )

    @app.get("/health")
    async def get_health() -> JSONResponse:
        if active_analyzer.ready:
            return JSONResponse(
                status_code=200,
                content={"schema_version": 1, "status": "ready"},
            )
        return JSONResponse(
            status_code=503,
            content={
                "schema_version": 1,
                "error": {
                    "code": "model_not_loaded",
                    "message": "Model is not loaded",
                },
            },
        )

    @app.get("/info")
    async def get_info() -> dict[str, object]:
        return build_info_response(settings.service_version)

    @app.get("/models")
    async def get_models(request: Request) -> JSONResponse:
        schema_version = request.query_params.get("schema_version")
        if schema_version is None:
            return error_response(
                status_code=422,
                request_id=request.state.request_id,
                code="invalid_request",
                message="schema_version is required",
            )
        if schema_version != "1":
            return error_response(
                status_code=422,
                request_id=request.state.request_id,
                code="unsupported_schema_version",
                message="Schema version is unsupported",
            )
        return JSONResponse(
            content=build_models_response(
                model_id=active_analyzer.model_id,
                model_version=active_analyzer.model_version,
                embedding_dimension=active_analyzer.embedding_dimension,
                ready=active_analyzer.ready,
            )
        )

    @app.post("/analyze")
    async def analyze(request: Request) -> JSONResponse:
        if not active_analyzer.ready:
            return error_response(
                status_code=503,
                request_id=request.state.request_id,
                code="model_not_loaded",
                message="Model is not loaded",
            )
        if not inference_slot.try_acquire():
            return error_response(
                status_code=429,
                request_id=request.state.request_id,
                code="busy",
                message="Analysis is already in progress",
                headers={"Retry-After": "1"},
            )
        try:
            analysis_input = AnalysisInput(
                body=await request.body(),
                content_type=request.headers.get("content-type", ""),
            )
            async with asyncio.timeout(inference_timeout_seconds):
                result = await active_analyzer.analyze(analysis_input)
        except TimeoutError:
            return error_response(
                status_code=500,
                request_id=request.state.request_id,
                code="internal_failure",
                message="Analysis deadline exceeded",
            )
        except Exception:
            return error_response(
                status_code=500,
                request_id=request.state.request_id,
                code="internal_failure",
                message="Analysis failed",
            )
        finally:
            inference_slot.release()
        return JSONResponse(content=result)

    return app
