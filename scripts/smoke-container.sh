#!/usr/bin/env bash

set -euo pipefail

image="${1:-growspace-vision:issue81}"
container_name="growspace-vision-smoke-${RANDOM}-$$"
smoke_dir="$(mktemp -d)"

cleanup() {
  docker rm --force "${container_name}" >/dev/null 2>&1 || true
  rm -rf "${smoke_dir}"
}
trap cleanup EXIT

docker run \
  --detach \
  --name "${container_name}" \
  --publish 127.0.0.1::8099 \
  --env GROWSPACE_VISION_TOKEN=smoke-test-secret \
  "${image}" >/dev/null

for _attempt in $(seq 1 25); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${container_name}")" != "true" ]]; then
    docker logs "${container_name}" >&2
    exit 1
  fi

  host_port="$(docker port "${container_name}" 8099/tcp | awk -F: 'NR == 1 { print $NF }')"
  health_status="$(
    curl \
      --silent \
      --output "${smoke_dir}/health.json" \
      --write-out '%{http_code}' \
      "http://127.0.0.1:${host_port}/health" || true
  )"
  if [[ "${health_status}" == "503" ]]; then
    jq --exit-status '.error.code == "model_not_loaded"' \
      "${smoke_dir}/health.json" >/dev/null
    curl \
      --fail \
      --silent \
      --header 'Authorization: Bearer smoke-test-secret' \
      "http://127.0.0.1:${host_port}/info" \
      | jq --exit-status '.service_name == "growspace_manager_vision"' >/dev/null
    exit 0
  fi

  sleep 0.2
done

docker logs "${container_name}" >&2
exit 1
