#!/usr/bin/env bash

set -euo pipefail

target="${1:-all}"
case "${target}" in
  amd64) architectures=(amd64) ;;
  arm64) architectures=(arm64) ;;
  all) architectures=(amd64 arm64) ;;
  *) echo "usage: $0 [amd64|arm64|all]" >&2; exit 2 ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The App version comes from growspace_vision/config.yaml, which is what the
# Home Assistant App store reads and therefore what the published GHCR tag
# has to be. The model version is a different number; see scripts/app-version.sh.
app_version="$("${root}/scripts/app-version.sh")"

if [[ " ${architectures[*]} " == *" arm64 "* ]]; then
  buildx_platforms="$(docker buildx inspect --bootstrap)"
  case "${buildx_platforms}" in
    *linux/arm64*) ;;
    *)
      echo "arm64 execution is unavailable; register a pinned binfmt handler:" >&2
      echo "docker run --privileged --rm tonistiigi/binfmt:qemu-v10.0.4 --install arm64" >&2
      exit 1
      ;;
  esac
fi

for arch in "${architectures[@]}"; do
  python3 "${root}/scripts/prepare-build-inputs.py" \
    --lock "${root}/packaging/locks/${arch}.lock" \
    --output "${root}/.build-inputs/${arch}"
  python3 "${root}/scripts/verify-build-inputs.py" \
    --manifest "${root}/.build-inputs/${arch}/manifest.json" \
    --root "${root}/.build-inputs/${arch}"

  docker buildx build \
    --platform "linux/${arch}" \
    --network none \
    --provenance false \
    --build-arg "APP_VERSION=${app_version}" \
    --load \
    --tag "growspace-vision:${app_version}-${arch}" \
    "${root}"

  "${root}/scripts/smoke-container.sh" \
    "growspace-vision:${app_version}-${arch}" "${arch}" "${app_version}"
done
