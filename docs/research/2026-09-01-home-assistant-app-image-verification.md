# Home Assistant App image verification

Verification for [workspace issue 85](https://github.com/Venosta-web/growspace_manager_workspace/issues/85),
performed on 2026-09-01 on an amd64 host.

## Reproducible build and runtime proof

The complete gate ran with:

```bash
./scripts/build-app-images.sh all
```

The command prepared only the architecture lock's named inputs, verified every byte,
built with Docker networking disabled, and exercised each resulting image with a
read-only root filesystem and `--network none`.

| Image | Execution | Local OCI image digest | `/analyze` | Memory sample |
|---|---|---|---:|---:|
| `growspace-vision:1.0.0-amd64` | native amd64 | `sha256:9f082ff8c5e5b71ce8893229dea111d01a1d2056065874de2d984c8d61310fa3` | 0.034376 s | 111 MiB |
| `growspace-vision:1.0.0-arm64` | QEMU on amd64 | `sha256:9e67680d464fae9459ee09f175d73a10adca8e4d6d09412fe38f60d4c078d069` | 9.138726 s | 279.8 MiB |

Both smoke runs checked the kernel architecture, `/health`, authenticated `/info` and
`/models`, and a real authenticated `/analyze` response containing a 384-dimensional
embedding. Container inspection confirmed `NetworkMode=none`. The image audit also
confirmed the locked model SHA-256, DINOv2 and FlatBuffers Apache-2.0 texts, ONNX
Runtime's licence and third-party notices, and the 40 locked inputs in each SPDX SBOM.

The memory values are point-in-time `docker stats` samples, not peak measurements. The
ARM64 run proves image compatibility and contract execution under emulation only;
physical ARM latency and memory remain explicitly unmeasured.

## Source validation

- Full suite with the exact packaged model: 79 tests passed.
- Ruff lint and formatting checks passed for `src`, `tests`, and `scripts`.
- Strict mypy passed for `src`, packaging scripts, and the packaging tests.
- App/repository YAML parsed successfully, shell entrypoints passed `bash -n`, and
  `git diff --check` reported no whitespace errors.
