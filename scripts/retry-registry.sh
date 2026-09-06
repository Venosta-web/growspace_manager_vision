#!/usr/bin/env bash

# Run one registry command, retrying the transient failures GHCR answers with.
#
# Release run 33997608337 pushed every layer of the arm64 App image and then
# lost the whole release to a single `received unexpected HTTP status: 500
# Internal Server Error` on the final manifest PUT. Nothing about the build,
# the smoke test or the credentials was involved — the amd64 job published the
# same commit in the same run. Recovery was a human noticing and dispatching
# the workflow by hand.
#
# Every registry call in `Release` runs once and is load-bearing: a push, the
# `imagetools create` that composes the generic tag, the `imagetools inspect`
# that reads its digest, and the probe that decides whether the version is
# already published. Retrying them is safe because a tag is only claimed once
# its manifest lands, so a failed attempt leaves nothing behind to conflict
# with — which is exactly why the manual re-run worked.
#
# The wrapped command's own stdout is passed through untouched, so a caller can
# still capture a digest through this helper; everything this script says about
# attempts goes to stderr.
#
#   ./scripts/retry-registry.sh docker push "$tag"
#   ./scripts/retry-registry.sh --budget   # worst-case seconds spent sleeping
#
# `VISION_REGISTRY_ATTEMPTS` and `VISION_REGISTRY_DELAY_SECONDS` exist so a test
# can drive the real thing without waiting out a real backoff. CI uses the
# defaults, and `--budget` is how the workflow's own tests check that exhausting
# them cannot approach a job's `timeout-minutes`.

set -euo pipefail

attempts="${VISION_REGISTRY_ATTEMPTS:-3}"
delay="${VISION_REGISTRY_DELAY_SECONDS:-5}"

if [[ ! "${attempts}" =~ ^[0-9]+$ ]] || ((attempts < 1)); then
  echo "retry-registry: VISION_REGISTRY_ATTEMPTS must be a positive integer" >&2
  exit 2
fi

if [[ ! "${delay}" =~ ^[0-9]+$ ]]; then
  echo "retry-registry: VISION_REGISTRY_DELAY_SECONDS must be an integer" >&2
  exit 2
fi

# The backoff is linear: `delay` after the first failure, `2 * delay` after the
# second, and so on. The worst case is therefore the sum of those pauses, and a
# caller can ask for it rather than deriving it from the defaults.
budget=0
for ((step = 1; step < attempts; step++)); do
  budget=$((budget + delay * step))
done

if [[ "${1-}" == "--budget" ]]; then
  printf '%s\n' "${budget}"
  exit 0
fi

if (($# == 0)); then
  echo "retry-registry: no command given" >&2
  exit 2
fi

label="retry-registry: $*"
attempt=1

while true; do
  if "$@"; then
    echo "${label}: succeeded on attempt ${attempt} of ${attempts}" >&2
    exit 0
  else
    status=$?
  fi

  if ((attempt >= attempts)); then
    echo "${label}: failed on all ${attempts} attempts (exit ${status})" >&2
    exit "${status}"
  fi

  pause=$((delay * attempt))
  echo \
    "${label}: attempt ${attempt} of ${attempts} failed (exit ${status});" \
    "retrying in ${pause}s" >&2
  sleep "${pause}"
  attempt=$((attempt + 1))
done
