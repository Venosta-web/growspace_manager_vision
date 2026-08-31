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

## Service

The production service is an ASGI application with one public construction seam:
`growspace_vision.create_app`. Its current executable boundary provides:

- unauthenticated readiness at `GET /health`;
- bearer-authenticated `GET /info`, `GET /models`, and `POST /analyze`;
- one process-wide analysis slot with no queue and `429 busy` for concurrent work;
- a ten-second analysis deadline; and
- closed, request-correlated errors that do not expose tokens, paths, tracebacks, image
  bytes, or request metadata.

`POST /analyze` takes one closed `metadata` part and one JPEG or PNG `image` part. It
refuses anything else before measuring: a body above 10 MiB or 24 megapixels is
`413 image_too_large`, a format that is neither JPEG nor PNG is
`415 unsupported_image_format`, an undecodable body or metadata outside the contract is
`422`, and a model the process did not load is `503 model_not_loaded`. A request must
declare its `Content-Length`; that is the only bound the service can apply before
reading a body.

### The absolute frame quality floor

Accepted requests are decoded literally — no EXIF orientation, no colour management, no
resampling — and measured for the contract's three `QualitySignals` before any
inference. [ADR 0005](docs/adr/0005-the-frame-quality-gate-rejects-darkness-and-bounds-the-rest.md)
sets the floor this layer applies:

| condition                              | reason                 |
| -------------------------------------- | ---------------------- |
| `mean_luminance < 16`                  | `too_dark`             |
| `mean_absolute_gradient < 0.5`         | `low_detail`           |
| `clipped_pixel_fraction >= 0.90`       | `overexposed`          |
| `light_state` disagrees with the image | `light_state_mismatch` |

A frame reports every floor it fails. A rejection is a first-class `200` result with
`status: "rejected"`, its signals, its reasons, and no embedding — never an error and
never a silent drop — and it costs no inference, which is the whole reason the floor is
absolute. Everything relative to a camera's own past stays in Home Assistant's Quality
History; the service holds no history and applies only the rejections that need none.

These thresholds are service behaviour, not wire shape: they move with
`service_version`, never with `schema_version`.

The service intentionally starts with its model unavailable. The DINOv2 runtime ticket
supplies the analyzer behind the accepted branch; until then `/health` and `/analyze`
return `503 model_not_loaded` while `/info` and `/models` remain usable for negotiation.

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

`tests/test_growspace_vision_contract.py` remains dependency-free when run on its own
with the system Python; the service tests need the installed extra.
