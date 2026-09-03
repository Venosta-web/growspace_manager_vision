# Production model and multi-architecture runtime supply chain

Research resolution for [Lock the production model artifact and multi-architecture
runtime supply chain](https://github.com/Venosta-web/growspace_manager_workspace/issues/80),
under the destination and constraints in
[Deliver Growspace Vision V1 end to end](https://github.com/Venosta-web/growspace_manager_workspace/issues/79).

Date: 2026-08-31. External claims below use primary sources. Hashes, graph structure,
container manifests, and the experiment inventory were also checked directly; the
commands are recorded so implementation can turn them into gates.

## Decision

V1 ships the **existing measured bytes**, not a new export:

| Property | Locked value |
|---|---|
| Contract identity | `model_id = dinov2-vit-s-14-int8-onnx`; `model_version = 1.0.0` |
| Artifact repository | `onnx-community/dinov2-small` |
| Immutable repository revision | `8b1f705a3a7f6f062f6bdd21986c1583d3ef105d` |
| Path | `onnx/model_int8.onnx` |
| Size | `24,446,700` bytes |
| SHA-256 | `dfce54a839b491f395c516350ebb4a78f947e9170a6beac0f2bc5638e0f09d61` |
| Input | float32 NCHW `pixel_values`, dynamic height and width |
| Output used | token 0 of `last_hidden_state`, 384 floats, then L2-normalised |
| Runtime | `onnxruntime==1.29.0`, `CPUExecutionProvider` only |
| Container base | `ghcr.io/home-assistant/base-debian:trixie-2026.08.0@sha256:01e153da2c2579f2cf5010901da7bc31b1dd035921ea46ccaff22e521efa74a7` |
| Supported image platforms | `linux/amd64`, `linux/arm64` |

The ONNX Community [immutable tree](https://huggingface.co/onnx-community/dinov2-small/tree/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d)
and [original artifact upload](https://huggingface.co/onnx-community/dinov2-small/commit/ef1fb1005bfd7768839d18080f7038b403506f87)
publish the same size and LFS SHA-256. Downloading through the immutable `resolve` URL
and hashing locally reproduced that value. A build must fail closed on any size or hash
mismatch; it must never silently use `main`, a similarly named `*-ONNX` repository, or
a newly converted file.

The official source checkpoint is Meta's
[`facebook/dinov2-small` at `ed25f3a31f01632728cabb09d1542f84ab7b0056`](https://huggingface.co/facebook/dinov2-small/tree/ed25f3a31f01632728cabb09d1542f84ab7b0056).
Its `model.safetensors` is 88,249,960 bytes with SHA-256
`ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1`.
The ONNX repository names that checkpoint in `config.json`, but does **not** record the
exact source revision, exporter package lock, or invocation; its only tool-version clue
is `transformers_version = 4.45.0.dev0`. Therefore V1's reproducible unit is the pinned
ONNX byte stream above. The source checkpoint is provenance, not a promise that a fresh
conversion will be byte-identical.

`model_version = 1.0.0` binds the artifact bytes, preprocessing, token selection, and
normalisation below. Any change to one of those inputs needs corpus replay and a new
model version/Baseline Bucket. An ONNX Runtime security update may retain the model
version only after golden-vector and corpus-distance equivalence pass; otherwise it is
a model-version change too.

## Quantisation: correct the QDQ description

The selected file is **not a QDQ graph**, despite that wording in the model-selection
resolution. Direct graph inspection found 49 `DynamicQuantizeLinear`, 72
`MatMulInteger`, one `ConvInteger`, and no `DequantizeLinear` nodes. Its embedded model
metadata is `producer_name = onnx.quantize`, `producer_version = 0.1.0`, opset 14, and
`onnx.infer = onnxruntime.quant`.

The repository's pinned
[`quantize_config.json`](https://huggingface.co/onnx-community/dinov2-small/blob/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/quantize_config.json)
records `per_channel: true`, `reduce_range: true`, `is_symmetric: true`, and
`quant_type: 1`. Together with the graph, the precise description is **dynamic
integer-operator quantisation with per-channel symmetric signed-int8 reduced-range
weights and dynamically quantised activations**. This is a terminology and provenance
correction, not a reason to replace the artifact: all selection and corpus measurements
were performed against these exact integer-operator bytes. Re-exporting as QDQ would
be a new unmeasured model.

## Preprocessing is part of the model

Production must reproduce [`scratchpad/wf62/vision_lib.py`](../../scratchpad/wf62/vision_lib.py),
not blindly run the upstream processor configuration:

1. Start with the deterministic RGB image emitted by the image-decoding boundary.
2. Resize the **whole image** to `224 x 168` with bicubic resampling. Do not crop. Both
   dimensions are multiples of DINOv2's 14-pixel patch size.
3. Convert to float32 and divide by 255.
4. Per channel, subtract `[0.485, 0.456, 0.406]` and divide by
   `[0.229, 0.224, 0.225]`.
5. Transpose HWC to NCHW and add the batch dimension, producing `[1, 3, 168, 224]`.
6. Run the ONNX graph, select `last_hidden_state[0, 0, :]`, cast the 384 values to
   float64 for normalisation, and divide by their L2 norm.

The upstream
[`preprocessor_config.json`](https://huggingface.co/onnx-community/dinov2-small/blob/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/preprocessor_config.json)
instead describes shortest-edge 256 plus a 224-square centre crop. That was the
conventional comparison variant in the experiment, **not** the production geometry:
the measured V1 result used aspect-preserving `224 x 168` because the canopy fills the
frame. At that geometry the graph returns 192 patch tokens plus CLS, shaped
`[1, 193, 384]`.

The decoder and resize library versions belong in the service's hash-locked dependency
closure. Golden fixtures must cover decoded pixels, the input tensor, embedding length,
unit norm, and a tolerance-bounded reference vector on both architectures. A library
upgrade that changes pixels or crosses the distance-equivalence tolerance is not a
routine dependency bump.

## What the experiment actually ran

The corpus experiment records:

- the mutable name `onnx-community/dinov2-small/onnx/model_int8.onnx`, but no repository
  revision or checksum;
- `onnxruntime` 1.29.0 with `CPUExecutionProvider`, graph optimisations enabled, and
  `intra_op_num_threads = 8` for the 109-frame corpus;
- the preprocessing and output extraction above; and
- a separate fp32 control using `onnx/model.onnx`.

The earlier runtime-selection benchmark used four pinned Gracemont E-cores and four
intra-op threads; the corpus scripts used eight host threads. Production therefore
defaults to `intra_op_num_threads = 4`, `inter_op_num_threads = 1`, graph optimisation
`ORT_ENABLE_ALL`, and the CPU provider. Thread count is service runtime provenance, not
permission to change the model pipeline.

The experiment's local model files are untracked and no longer present, so their bytes
cannot be re-hashed after the fact. The model repository has not changed the selected
blob since its 2024-08-31 upload, making the pinned artifact the strong inference for
what ran, but not documentary proof. This is the provenance gap production closes with
the manifest, startup hash check, and golden/corpus replay. The published fp32 control
already showed every decisive AUC within 0.05, so this gap does not reopen the encoder
or quantisation choice.

## ONNX Runtime and architecture inputs

Pin `onnxruntime==1.29.0`, released as
[ONNX Runtime v1.29.0](https://github.com/microsoft/onnxruntime/releases/tag/v1.29.0).
The official [PyPI release metadata](https://pypi.org/pypi/onnxruntime/1.29.0/json)
requires Python 3.11 or newer and publishes CPython 3.13 manylinux 2.28 wheels for both
target architectures:

| Platform | Wheel | Size | SHA-256 |
|---|---|---:|---|
| `linux/amd64` | `onnxruntime-1.29.0-cp313-cp313-manylinux_2_28_x86_64.whl` | 23,136,817 | `e2128f31f449e922c62dbe5d8b6b7b079f0bcaf2d56a102fa203cb6e5bb5ab19` |
| `linux/arm64` | `onnxruntime-1.29.0-cp313-cp313-manylinux_2_28_aarch64.whl` | 20,816,263 | `d67673c5367727860922c5262d724472f1b5539fb7ccf4c81a638f9b71719803` |

Debian Trixie's
[`python3` package](https://packages.debian.org/trixie/python/python3) selects CPython
3.13 and is published for amd64 and arm64. The Home Assistant base image does not itself
contain Python; the packaging work must lock the selected Debian snapshot/package set
rather than run an unconstrained `apt-get` against a moving mirror. ORT also depends on
`flatbuffers`, `numpy>=1.21.6`, `packaging`, and `protobuf>=4.25.8`; the service and all
transitive dependencies must appear in per-architecture, hash-complete wheelhouse
locks. `pip install` in the image must use `--no-index --require-hashes`.

The base is Home Assistant's dated Debian Trixie release, not the rolling tag. Home
Assistant documents that `base-debian` is the glibc alternative and that its official
platforms are amd64 and arm64 in the
[`docker-base` README](https://github.com/home-assistant/docker-base). On 2026-08-31,
OCI manifest inspection established:

| Object | Digest |
|---|---|
| multi-architecture index | `sha256:01e153da2c2579f2cf5010901da7bc31b1dd035921ea46ccaff22e521efa74a7` |
| `linux/amd64` manifest | `sha256:88f7241f3c91775e16457778a79dc8155484c379c7f5e0c556c99ff99b3f11bf` |
| `linux/arm64` manifest | `sha256:d5eadceb6b0a2b32145065cc3dfd085e740e9805d1c443ca2f09bc4241f946e7` |

The amd64 image identifies itself as Home Assistant base version `2026.08.0`, Debian
13.6 Trixie, glibc 2.41. ORT's manylinux 2.28 floor is therefore satisfied. Pinning the
index digest lets the same Dockerfile resolve the right native image without mutable
architecture-prefixed tags.

Availability is not performance evidence. The arm64 base manifest and CPython wheel
exist, so a cross-built image and emulated architecture smoke test are supportable. No
physical ARM machine was available, and there is no primary-source benchmark for this
exact artifact/runtime/CPU pair. V1 must state arm64 latency and peak RSS as unmeasured;
QEMU results prove startup and contract compatibility only. Physical ARM performance
remains a release risk, exactly as map 79 records.

## Licence and notice bundle

The official Meta model card declares Apache-2.0, and the DINOv2 repository carries the
full [Apache License 2.0](https://github.com/facebookresearch/dinov2/blob/main/LICENSE)
with Meta copyright headers in source. The image/release must include:

- the DINOv2 Apache-2.0 licence and an attribution naming Meta Platforms, Inc., the
  official checkpoint revision, the ONNX Community conversion revision, and the exact
  model SHA-256;
- ONNX Runtime's [MIT licence](https://github.com/microsoft/onnxruntime/blob/v1.29.0/LICENSE)
  and its version-matched
  [`ThirdPartyNotices.txt`](https://github.com/microsoft/onnxruntime/blob/v1.29.0/ThirdPartyNotices.txt);
- licences/notices for the complete locked Python and Debian dependency closure; and
- a generated SBOM for each architecture, attached to the image/release alongside the
  model manifest.

The selected DINOv2 distribution has no separate upstream `NOTICE` file. Do not copy
the unrelated `LICENSE_XRAY_DINO_MODEL` added later to the DINOv2 source repository;
that licence is for a different X-Ray DINO model, not `facebook/dinov2-small`.

## Hermetic build and no-runtime-download gates

The production route is deliberately two-stage:

1. A source-preparation job reads a checked-in manifest of immutable URLs, sizes, and
   SHA-256 values; downloads the model, architecture wheelhouse, frozen Debian package
   closure, and licence inputs; verifies every byte; and emits a content-addressed
   build-context archive. Mirroring the model as a release asset is allowed only if the
   original SHA-256 is preserved.
2. The image build consumes only the pinned base digest and that verified archive.
   Application-layer build steps run with networking disabled. The final image contains
   the model, decoder/runtime dependencies, manifest, and notices; it contains no Hub,
   Transformers, Optimum, exporter, package-manager cache, or download code.

At service startup, verify the model size and SHA-256 before constructing the ORT
session. A mismatch leaves `/health` unready and the model `unavailable`; it must never
fall back to a fetch. CI must then run `/health`, `/info`, `/models`, and a golden
`/analyze` request with the final image under `--network=none`, for native amd64 and an
arm64 architecture smoke environment. A static egress scan is useful but is not the
proof: successful analysis with no network namespace is.

This research does not need a new Wayfinder ticket. The implementation responsibilities
already land cleanly in
[Implement the selected DINOv2 embedding runtime](https://github.com/Venosta-web/growspace_manager_workspace/issues/83)
(manifest, preprocessing, startup check, golden embedding) and
[Package the multi-architecture Home Assistant App](https://github.com/Venosta-web/growspace_manager_workspace/issues/85)
(base digest, Debian/wheel locks, notices, SBOM, hermetic build, amd64 proof and arm64
smoke). The release-readiness audit must retain physical ARM performance as an explicit
unmeasured risk rather than manufacturing a number.

## Reproduction commands

```bash
curl -fL \
  'https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model_int8.onnx?download=true' \
  -o model_int8.onnx
printf '%s  %s\n' \
  dfce54a839b491f395c516350ebb4a78f947e9170a6beac0f2bc5638e0f09d61 \
  model_int8.onnx | sha256sum --check --strict

docker buildx imagetools inspect \
  ghcr.io/home-assistant/base-debian:trixie-2026.08.0
```

The graph-node and ModelProto metadata inspection was performed on the verified local
artifact. Production should use an ONNX parser in tests to assert the input/output
contract and reject an accidental QDQ or fp32 replacement; runtime code should not need
the `onnx` package.
