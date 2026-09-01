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

`POST /analyze` takes one closed `metadata` part and one `image` part advertised and
decoded as JPEG or PNG. It refuses anything else before measuring: a body above 10 MiB
or 24 megapixels is `413 image_too_large`, an unsupported part media type or decoded
format is `415 unsupported_image_format`, and an undecodable body or metadata outside
the contract is `422`. An unknown model identity is also `422 invalid_request`; the
configured model being unavailable is `503 model_not_loaded`. A request must declare
its `Content-Length`; that is the only bound the service can apply before reading a
body.

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

### The bundled DINOv2 runtime

The process loads only the local model named by `GROWSPACE_VISION_MODEL_PATH` (default
`/opt/growspace-vision/models/model_int8.onnx`). The checked-in manifest fixes the
`onnx-community/dinov2-small` int8 artifact bytes, model identity, whole-frame
`224 x 168` bicubic preprocessing, ImageNet normalization, CLS-token selection,
384-value output, and float64 L2 normalization. ONNX Runtime 1.29.0 runs with only the
CPU provider, four intra-op threads, one inter-op thread, and full graph optimization.

Startup verifies the artifact's 24,446,700-byte size and SHA-256 before constructing an
ONNX session, then checks the graph's input/output identity. A missing, altered,
unloadable, or incompatible model leaves `/health` unready and `/models` unavailable;
the service never downloads a fallback. Cancellation at the ten-second service
deadline terminates the active ONNX run before the one-slot inference boundary is
released.

Set the per-install token and start one worker on the internal port:

```bash
export GROWSPACE_VISION_TOKEN="replace-with-a-generated-token"
export GROWSPACE_VISION_MODEL_PATH="/path/to/verified/model_int8.onnx"
growspace-vision
```

`GROWSPACE_VISION_SERVICE_VERSION` optionally overrides the reported service release
version. The process deliberately ignores environmental observations; none belongs in
the service configuration or request boundary.

## Home Assistant App images

The [`growspace_vision/config.yaml`](growspace_vision/config.yaml) wrapper exposes only
the internal App-network API. It requests no host mounts, device access, Supervisor or
Home Assistant API permission, Ingress, or published host port.

Because it publishes no host port, the App also owns its own credential.
[`growspace_vision/provision.py`](growspace_vision/provision.py) mints a per-install
bearer token under `/data` on first start and announces `{host, port, token}` to
Supervisor App discovery, which the integration pulls; the optional `access_token`
option overrides it for a manually configured endpoint, and `GROWSPACE_VISION_TOKEN`
overrides both when the image is run outside Supervisor. See
[ADR 0006](docs/adr/0006-the-app-mints-its-own-token-and-hands-it-over-through-discovery.md).

The image build is deliberately split at the network boundary. Preparation downloads
only the URLs in `packaging/locks/{amd64,arm64}.lock`, verifies every size and SHA-256,
and materializes an ignored `.build-inputs/<arch>` directory. Docker then consumes the
exact closed set under `--network none`, installs the dated Debian and hash-complete
wheel closures locally, and bundles the verified model, licence material, notices, and
an architecture-specific SPDX SBOM.

Build and smoke both images:

```bash
./scripts/build-app-images.sh all
```

The smoke gate starts each target architecture with a read-only root filesystem and
`--network none`, checks the architecture from inside the container, then exercises
`/health`, `/info`, `/models`, and a real `/analyze` request. arm64 execution under QEMU
is a compatibility check only; physical ARM latency and memory remain unmeasured.

Home Assistant's current App builder no longer reads `build.yaml`; the pinned
multi-architecture base, build arguments, and labels therefore live directly in the
Dockerfile. [`repository.yaml`](repository.yaml) makes this repository discoverable as
an App repository, while the generic image reference in `config.yaml` is ready for the
separate publication gate.

## Verify the V1 contract

Create an isolated environment, install the service test extra, and run the full suite:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The suite never fetches a model. To run the exact-artifact golden and process-startup
tests, prepare the locked bytes separately and provide their local path:

```bash
GROWSPACE_VISION_TEST_MODEL_PATH=/path/to/verified/model_int8.onnx \
  PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

`tests/test_growspace_vision_contract.py` remains dependency-free when run on its own
with the system Python; the service tests need the installed extra.
