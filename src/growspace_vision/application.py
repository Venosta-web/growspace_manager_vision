"""ASGI application for Growspace Vision."""

import asyncio
from collections.abc import Awaitable, Callable
from secrets import compare_digest
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import Response

from growspace_vision.analysis import (
    Analyzer,
    InferenceSlot,
    analyze_frame,
)
from growspace_vision.contract import build_info_response, build_models_response
from growspace_vision.images import (
    MAX_IMAGE_BYTES,
    ImageTooLarge,
    UndecodableImage,
    UnsupportedImageFormat,
)
from growspace_vision.metadata import (
    AnalyzeMetadata,
    InvalidMetadata,
    UnsupportedSchemaVersion,
    parse_metadata,
)
from growspace_vision.responses import error_response
from growspace_vision.runtime import load_production_analyzer
from growspace_vision.settings import ServiceSettings

# The image is bounded by the contract; the envelope around it is not, so the
# service allows one small, fixed multipart overhead and refuses a larger body
# before it reads or spools a single byte of it.
MULTIPART_OVERHEAD_ALLOWANCE: Final = 64 * 1024
MAX_REQUEST_BYTES: Final = MAX_IMAGE_BYTES + MULTIPART_OVERHEAD_ALLOWANCE
_ANALYZE_PARTS: Final = frozenset({"metadata", "image"})
_IMAGE_MEDIA_TYPES: Final = frozenset({"image/jpeg", "image/png"})


class InvalidAnalyzeRequest(ValueError):
    """The multipart envelope carrying one Vision Analysis is not usable."""


# Every way one analysis can fail, and the closed error it becomes. A `None` message
# defers to the exception's own text, which is authored here and never quotes the
# request. Order matters only where one failure subclasses another.
_ANALYSIS_FAILURES: Final[tuple[tuple[type[Exception], int, str, str | None], ...]] = (
    (
        UnsupportedImageFormat,
        415,
        "unsupported_image_format",
        "Image must be JPEG or PNG",
    ),
    (ImageTooLarge, 413, "image_too_large", "Image exceeds the service limits"),
    (UndecodableImage, 422, "invalid_request", "Image could not be decoded"),
    (
        UnsupportedSchemaVersion,
        422,
        "unsupported_schema_version",
        "Schema version is unsupported",
    ),
    (InvalidMetadata, 422, "invalid_request", None),
    (InvalidAnalyzeRequest, 422, "invalid_request", None),
    (
        MultiPartException,
        422,
        "invalid_request",
        "Request is not a readable multipart/form-data body",
    ),
    (TimeoutError, 500, "internal_failure", "Analysis deadline exceeded"),
)


def create_app(
    settings: ServiceSettings,
    *,
    analyzer: Analyzer | None = None,
    inference_timeout_seconds: float = 10.0,
) -> FastAPI:
    """Create an isolated service application from explicit settings."""

    active_analyzer = analyzer or load_production_analyzer(settings.model_path)
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
        request_id = request.state.request_id
        declared_length = _declared_body_length(request)
        if declared_length is None:
            return error_response(
                status_code=422,
                request_id=request_id,
                code="invalid_request",
                message="Request must declare its Content-Length",
            )
        if declared_length > MAX_REQUEST_BYTES:
            return error_response(
                status_code=413,
                request_id=request_id,
                code="image_too_large",
                message="Image exceeds the service limits",
            )
        if not inference_slot.try_acquire():
            return error_response(
                status_code=429,
                request_id=request_id,
                code="busy",
                message="Analysis is already in progress",
                headers={"Retry-After": "1"},
            )
        try:
            async with asyncio.timeout(inference_timeout_seconds):
                metadata_body, image_body = await _read_analyze_parts(request)
                metadata = parse_metadata(metadata_body)
                if not _names_the_loaded_model(metadata, active_analyzer):
                    return error_response(
                        status_code=422,
                        request_id=request_id,
                        code="invalid_request",
                        message="Requested model is unknown",
                    )
                if not active_analyzer.ready:
                    return error_response(
                        status_code=503,
                        request_id=request_id,
                        code="model_not_loaded",
                        message="The requested model is not loaded",
                    )
                result = await analyze_frame(
                    request_id=request_id,
                    metadata=metadata,
                    image_body=image_body,
                    analyzer=active_analyzer,
                )
        except Exception as error:
            return _analysis_failure(request_id, error)
        finally:
            inference_slot.release()
        return JSONResponse(content=result)

    return app


def _analysis_failure(request_id: str, error: Exception) -> JSONResponse:
    """Map one analysis failure onto the closed V1 error set.

    Anything not named here is an internal defect, and it is reported as one rather
    than as a diagnosis of the caller's request.
    """

    for failure, status_code, code, message in _ANALYSIS_FAILURES:
        if isinstance(error, failure):
            return error_response(
                status_code=status_code,
                request_id=request_id,
                code=code,
                message=message or str(error),
            )
    return error_response(
        status_code=500,
        request_id=request_id,
        code="internal_failure",
        message="Analysis failed",
    )


def _declared_body_length(request: Request) -> int | None:
    """Return the declared body length, or None when the request does not declare one.

    A declared length is required rather than optional: Starlette spools file parts
    to disk without consulting its own part limit, so an undeclared streaming body
    is the one shape this service cannot bound before reading it.
    """

    declared_length = request.headers.get("content-length")
    if declared_length is None or not declared_length.isdigit():
        return None
    return int(declared_length)


def _names_the_loaded_model(metadata: AnalyzeMetadata, analyzer: Analyzer) -> bool:
    """Require the caller's negotiated model to be the one this process loaded."""

    return (
        metadata.model_id == analyzer.model_id
        and metadata.model_version == analyzer.model_version
    )


async def _read_analyze_parts(request: Request) -> tuple[bytes, bytes]:
    """Return the metadata and image bodies of one Vision Analysis request."""

    media_type = request.headers.get("content-type", "").partition(";")[0].strip()
    if media_type.lower() != "multipart/form-data":
        raise InvalidAnalyzeRequest("Request must be multipart/form-data")
    async with request.form(
        max_files=2, max_fields=2, max_part_size=MAX_REQUEST_BYTES
    ) as form:
        parts = form.multi_items()
        if len(parts) != 2 or {name for name, _ in parts} != _ANALYZE_PARTS:
            raise InvalidAnalyzeRequest(
                "Request must carry exactly one metadata part and one image part"
            )
        image = form["image"]
        if not isinstance(image, UploadFile):
            raise InvalidAnalyzeRequest("Image part must be sent as a file")
        image_media_type = (image.content_type or "").partition(";")[0].strip().lower()
        if image_media_type not in _IMAGE_MEDIA_TYPES:
            raise UnsupportedImageFormat
        metadata = form["metadata"]
        metadata_body = (
            await metadata.read()
            if isinstance(metadata, UploadFile)
            else metadata.encode("utf-8")
        )
        return metadata_body, await image.read()
