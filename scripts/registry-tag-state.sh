#!/usr/bin/env bash

# Say whether the App tag the store will pull is already published — or refuse
# to answer when the registry never actually said.
#
# `Release`'s first job decides whether to build at all by probing the generic
# tag. It used to run `docker buildx imagetools inspect` with both streams
# thrown away and read *any* non-zero exit as "not published", which makes a
# 404 and a `500 Internal Server Error` the same answer. Run 33997608337 is the
# proof that 500s reach this registry, so a docs-only merge to `main` — the
# case the guard exists to support — landing while GHCR is erroring would have
# reported a published version as absent, rebuilt it from a different commit,
# and pushed over bytes users already have. The guard was defeated by the
# failure mode most likely to trigger it, and the run looked ordinary.
#
# So classify what was actually seen. `published` and `absent` go to stdout
# with exit 0. Anything else — the registry unreachable, an unexpected status,
# a credential problem, a phrasing this does not recognise — names what it saw
# on stderr and exits non-zero, failing the job instead of guessing the answer
# that overwrites a release.
#
#   ./scripts/registry-tag-state.sh ghcr.io/venosta-web/growspace-manager-vision:1.0.1
#
# `VISION_REGISTRY_INSPECT` overrides the command that does the probing, so a
# test can drive the real classifier against a stubbed registry rather than
# asserting that the workflow mentions one. CI uses the default.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The status an unclassifiable answer exits with, distinct from the 2 a
# misuse exits with so a caller can tell "you called this wrong" from "the
# registry would not say".
INDETERMINATE=3

# The phrasings that mean the tag is genuinely not there: buildx's own message
# for a manifest the registry answered 404 for, and the two OCI distribution
# error codes underneath it. Matching is case-insensitive because a registry
# may return either `MANIFEST_UNKNOWN` or its prose form.
#
# Everything else is indeterminate on purpose, including an absence phrased in
# a way this list does not know. That direction is the safe one: an unrecognised
# absence costs a red run a human resolves in a minute, while a registry error
# mistaken for an absence silently republishes a version someone is running.
ABSENT_PHRASINGS=(
  ': not found'
  'manifest unknown'
  'name unknown'
)

probe() {
  local reference="$1"
  local -a inspect
  local output status phrasing

  read -r -a inspect \
    <<<"${VISION_REGISTRY_INSPECT:-docker buildx imagetools inspect}"

  # Both streams are kept rather than discarded — the classification is in the
  # error text, and the manifest is worth having in the log when there is one.
  status=0
  output="$("${inspect[@]}" "${reference}" 2>&1)" || status=$?

  if ((status == 0)); then
    printf '%s\n' "${output}" >&2
    printf 'published\n'
    return 0
  fi

  for phrasing in "${ABSENT_PHRASINGS[@]}"; do
    if grep -qiF -- "${phrasing}" <<<"${output}"; then
      printf 'absent\n'
      return 0
    fi
  done

  {
    echo "registry-tag-state: cannot tell whether ${reference} is published."
    echo "registry-tag-state: the probe exited ${status} saying:"
    printf '%s\n' "${output}"
  } >&2
  return "${INDETERMINATE}"
}

if [[ "${1-}" == "--probe" ]]; then
  shift
  probe "$@" || exit $?
  exit 0
fi

reference="${1-}"

if [[ -z "${reference}" ]]; then
  echo "registry-tag-state: no image reference given" >&2
  exit 2
fi

# Only an indeterminate answer is worth asking again, and the probe exits
# non-zero for exactly that — so wrapping it in the retry helper retries the
# blips and nothing else. A definitive answer ends on the first attempt, which
# is why a version being released for the first time now costs no backoff at
# all where the old probe failed every attempt before concluding the obvious.
exec "${here}/retry-registry.sh" \
  "${here}/$(basename "${BASH_SOURCE[0]}")" --probe "${reference}"
