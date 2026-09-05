#!/usr/bin/env bash

# Print the Docker architecture names the App declares, one per line.
#
# Home Assistant names architectures its own way in `growspace_vision/config.yaml`
# (`aarch64`), Docker and GHCR name them another (`arm64`). The App store reads
# the first and the registry serves the second, so the mapping is written down
# once, here, and the release composes its multi-architecture manifest from it
# rather than from a list someone has to remember to extend.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="${root}/growspace_vision/config.yaml"

declared="$(awk '
  /^arch:/ { in_list = 1; next }
  in_list && /^[[:space:]]*-[[:space:]]*/ {
    sub(/^[[:space:]]*-[[:space:]]*/, "")
    print
    next
  }
  in_list { exit }
' "${config}")"

if [[ -z "${declared}" ]]; then
  echo "No architectures declared in ${config}" >&2
  exit 1
fi

while read -r architecture; do
  case "${architecture}" in
    aarch64) printf 'arm64\n' ;;
    amd64) printf 'amd64\n' ;;
    *)
      echo "No published image is built for '${architecture}'" >&2
      exit 1
      ;;
  esac
done <<<"${declared}"
