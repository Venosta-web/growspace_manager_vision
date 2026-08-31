# Growspace Vision

Growspace Vision is the local, stateless image-analysis service for Growspace
Manager. It analyzes one camera snapshot at a time and returns a model-versioned
visual embedding or a first-class frame-quality rejection. Home Assistant owns
scheduling, history, baseline comparison, interpretation, and alerting.

This repository is the source of truth for the service boundary and its supporting
research:

- [`CONTEXT.md`](CONTEXT.md) defines the shared domain language.
- [`contracts/growspace-vision/v1/`](contracts/growspace-vision/v1/) contains the
  normative OpenAPI 3.1 contract and executable fixtures.
- [`docs/adr/`](docs/adr/) records the accepted boundary and baseline decisions.
- [`docs/research/`](docs/research/) and [`scratchpad/`](scratchpad/) preserve the
  experiments behind those decisions.

The cross-repository roadmap and issue tracker remain in
[`growspace_manager_workspace`](https://github.com/Venosta-web/growspace_manager_workspace).

## Service scaffold

The production service is an ASGI application with one public construction seam:
`growspace_vision.create_app`. Its current executable boundary provides:

- unauthenticated readiness at `GET /health`;
- bearer-authenticated `GET /info`, `GET /models`, and `POST /analyze`;
- one process-wide analysis slot with no queue and `429 busy` for concurrent work;
- a ten-second analysis deadline; and
- closed, request-correlated errors that do not expose tokens, paths, tracebacks, image
  bytes, or request metadata.

The service intentionally starts with its model unavailable. The image-decoding,
frame-quality, and DINOv2 runtime tickets supply the analyzer behind this boundary;
until then `/health` and `/analyze` return `503 model_not_loaded` while `/info` and
`/models` remain usable for negotiation.

Set the per-install token and start one worker on the internal port:

```bash
export GROWSPACE_VISION_TOKEN="replace-with-a-generated-token"
growspace-vision
```

`GROWSPACE_VISION_SERVICE_VERSION` optionally overrides the reported service release
version. The process deliberately ignores environmental observations; none belongs in
the service configuration or request boundary.

The checked-in Dockerfile is the executable container skeleton on the pinned Home
Assistant Debian base. The App-packaging ticket replaces its online package install
with the hash-complete, architecture-specific wheelhouse and licence bundle required
for the final no-network build.

## Verify the V1 contract

Create an isolated environment, install the service test extra, and run the full suite:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The original contract-only tests remain dependency-free when run with the system
Python.
