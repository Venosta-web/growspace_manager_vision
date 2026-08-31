"""Closed V1 error responses."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi.responses import JSONResponse


def error_response(
    *,
    status_code: int,
    request_id: str,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build the only wire shape used for service failures."""

    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "schema_version": 1,
            "request_id": request_id,
            "error": {"code": code, "message": message},
        },
    )
