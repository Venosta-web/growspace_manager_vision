#!/usr/bin/env bash

# Fail when Home Assistant's vendored copy of the V1 fixtures no longer matches
# the contract this repository owns.
#
# Growspace Manager is public and this repository is private, so the comparison
# cannot run in the backend's CI without a credential. It runs here instead,
# beside the contract it protects: a shallow, unauthenticated clone of the public
# backend is enough, and the comparison itself is the backend's own helper, so
# there is one implementation of "what vendoring means" rather than two.

set -euo pipefail

repository="${GROWSPACE_BACKEND_REPO:-https://github.com/Venosta-web/growspace_manager.git}"
ref="${GROWSPACE_BACKEND_REF:-prerelease}"
vision_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper_path="tests/utils/vision_contract_fixtures.py"

backend_root="${GROWSPACE_BACKEND_ROOT:-}"
if [ -n "${backend_root}" ]; then
  backend_root="$(cd "${backend_root}" && pwd)"
  source_label="${backend_root} (GROWSPACE_BACKEND_ROOT)"
  echo "backend checkout: ${source_label}"
else
  clone_dir="$(mktemp -d)"
  trap 'rm -rf "${clone_dir}"' EXIT
  source_label="${repository}@${ref}"
  echo "backend checkout: ${source_label}"
  git clone --quiet --depth 1 --branch "${ref}" --filter=blob:none --sparse \
    "${repository}" "${clone_dir}/backend"
  git -C "${clone_dir}/backend" sparse-checkout set \
    tests/fixtures/vision tests/utils >/dev/null
  backend_root="${clone_dir}/backend"
fi

if [ ! -f "${backend_root}/${helper_path}" ]; then
  cat >&2 <<EOF
backend fixture boundary: ${helper_path} is missing from ${source_label}

The comparison is the backend's own helper. If it moved, point this check at the
new path; do not drop the check.
EOF
  exit 1
fi

if python3 "${backend_root}/${helper_path}" \
  --vision-root "${vision_root}" --backend-root "${backend_root}"; then
  exit 0
fi

cat >&2 <<EOF

Growspace Manager vendors these fixtures byte for byte, and its parser tests run
against its own copy — so stale vendored bytes let the wire shape drift without
either repository noticing. That is what this check exists to make visible.

To clear it, copy the manifest-owned files from
  contracts/growspace-vision/v1/fixtures/
into growspace_manager
  tests/fixtures/vision/growspace-vision/v1/
and land that on ${ref}, updating the provenance commit in that directory's
README. The backend can vendor from this branch before it merges; it is copying
bytes, not depending on a merged commit.
EOF
exit 1
