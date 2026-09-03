"""Container and console entrypoint for Growspace Vision."""

import uvicorn
from fastapi import FastAPI

from growspace_vision.application import create_app
from growspace_vision.settings import ServiceSettings


def application() -> FastAPI:
    """Construct the ASGI application from process configuration."""

    return create_app(ServiceSettings.from_env())


def main() -> None:
    """Run one process so the application-wide inference slot stays singular."""

    uvicorn.run(
        "growspace_vision.__main__:application",
        factory=True,
        host="0.0.0.0",
        port=8099,
        workers=1,
        access_log=False,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
