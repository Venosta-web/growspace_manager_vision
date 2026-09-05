#!/usr/bin/env bash

# Print the App version: the number the Home Assistant App store reads off
# `growspace_vision/config.yaml`, the GHCR tag the store then pulls, and the
# `service_version` the running service reports back through `/info`. It is
# declared once, there, and every build, smoke and release step asks for it
# here rather than spelling it again.
#
# This is NOT the model version. That one lives in
# `src/growspace_vision/model_manifest.json` and `analysis.py`, is textually
# identical to this today, and identifies the embeddings that every stored
# Baseline Bucket and Framing Epoch in a user's evidence store is keyed to.
# Moving it re-labels comparison history that cannot be rebuilt, so nothing
# that bumps the App version may touch it.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="${root}/growspace_vision/config.yaml"

version="$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
  "${config}")"

if [[ -z "${version}" ]]; then
  echo "No App version declared in ${config}" >&2
  exit 1
fi

printf '%s\n' "${version}"
