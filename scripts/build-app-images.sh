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
    --load \
    --tag "growspace-vision:1.0.0-${arch}" \
    "${root}"

  "${root}/scripts/smoke-container.sh" \
    "growspace-vision:1.0.0-${arch}" "${arch}"
done
