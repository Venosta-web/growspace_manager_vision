#!/usr/bin/env bash

set -euo pipefail

image="${1:-growspace-vision:1.0.0-amd64}"
expected_arch="${2:-amd64}"
case "${expected_arch}" in
  amd64) kernel_arch=x86_64 ;;
  arm64) kernel_arch=aarch64 ;;
  *) echo "expected architecture must be amd64 or arm64" >&2; exit 2 ;;
esac

container_name="growspace-vision-smoke-${RANDOM}-$$"
provisioned_name="growspace-vision-provisioned-${RANDOM}-$$"
smoke_dir="$(mktemp -d)"

cleanup() {
  docker rm --force "${container_name}" "${provisioned_name}" >/dev/null 2>&1 || true
  rm -rf "${smoke_dir}"
}
trap cleanup EXIT

printf '%s' \
  'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAZklEQVR4nO3PMQ3AQBDAsLZoDuJBfTiFYb0UD9nz7u7MnHMu7fdcrgGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQHtBzhlX2DTuLdEAAAAAElFTkSuQmCC' \
  | base64 --decode >"${smoke_dir}/frame.png"
cat >"${smoke_dir}/metadata.json" <<'JSON'
{
  "schema_version": 1,
  "camera_id": "camera.packaging_smoke",
  "growspace_id": "packaging-smoke",
  "captured_at": "2026-08-31T08:30:00Z",
  "light_state": "on",
  "model_id": "dinov2-vit-s-14-int8-onnx",
  "model_version": "1.0.0"
}
JSON

docker run \
  --detach \
  --name "${container_name}" \
  --platform "linux/${expected_arch}" \
  --network none \
  --read-only \
  --tmpfs /run:rw,exec,nosuid,size=16m \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --env GROWSPACE_VISION_TOKEN=smoke-test-secret \
  "${image}" >/dev/null

test "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "${container_name}")" = none
test "$(docker exec "${container_name}" uname -m)" = "${kernel_arch}"

for _attempt in $(seq 1 100); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${container_name}")" != true ]]; then
    docker logs "${container_name}" >&2
    exit 1
  fi
  status="$(docker exec "${container_name}" curl --silent --output /tmp/health.json \
    --write-out '%{http_code}' http://127.0.0.1:8099/health || true)"
  [[ "${status}" == 200 ]] && break
  sleep 0.2
done
test "${status}" = 200
docker exec "${container_name}" jq --exit-status \
  '.schema_version == 1 and .status == "ready"' /tmp/health.json >/dev/null

docker exec "${container_name}" curl --fail --silent \
  --header 'Authorization: Bearer smoke-test-secret' \
  http://127.0.0.1:8099/info \
  | jq --exit-status \
      '.service_name == "growspace_manager_vision" and .service_version == "1.0.0"' \
      >/dev/null

docker exec "${container_name}" curl --fail --silent \
  --header 'Authorization: Bearer smoke-test-secret' \
  'http://127.0.0.1:8099/models?schema_version=1' \
  | jq --exit-status \
      '.models[0].model_id == "dinov2-vit-s-14-int8-onnx" and
       .models[0].model_version == "1.0.0" and
       .models[0].embedding_dimension == 384 and
       .models[0].state == "loaded"' >/dev/null

docker exec --interactive "${container_name}" sh -c 'cat >/tmp/metadata.json' \
  <"${smoke_dir}/metadata.json"
docker exec --interactive "${container_name}" sh -c 'cat >/tmp/frame.png' \
  <"${smoke_dir}/frame.png"
analyze_metrics="$(docker exec "${container_name}" curl --fail --silent \
  --output /tmp/analyze.json \
  --write-out '%{time_total}' \
  --header 'Authorization: Bearer smoke-test-secret' \
  --form 'metadata=@/tmp/metadata.json;type=application/json' \
  --form 'image=@/tmp/frame.png;type=image/png' \
  http://127.0.0.1:8099/analyze)"
docker exec "${container_name}" jq --exit-status \
  '.status == "analyzed" and
   .model.model_id == "dinov2-vit-s-14-int8-onnx" and
   .embedding.dimension == 384 and
   (.embedding.values | length) == 384 and
   (.quality.reasons | length) == 0' /tmp/analyze.json >/dev/null

memory="$(docker stats --no-stream --format '{{.MemUsage}}' "${container_name}")"

# The App's own credential lifecycle: no token is supplied, so the image must
# mint one under /data, keep it owner-only, enforce it, and reuse it on the
# next start. Discovery itself needs a Supervisor and is covered by the
# packaging tests; this proves the half that lives in the image.
data_dir="${smoke_dir}/data"
mkdir "${data_dir}"

docker run \
  --detach \
  --name "${provisioned_name}" \
  --platform "linux/${expected_arch}" \
  --network none \
  --read-only \
  --tmpfs /run:rw,exec,nosuid,size=16m \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --volume "${data_dir}:/data" \
  "${image}" >/dev/null

for _attempt in $(seq 1 100); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "${provisioned_name}")" != true ]]; then
    docker logs "${provisioned_name}" >&2
    exit 1
  fi
  status="$(docker exec "${provisioned_name}" curl --silent --output /dev/null \
    --write-out '%{http_code}' http://127.0.0.1:8099/health || true)"
  [[ "${status}" == 200 ]] && break
  sleep 0.2
done
test "${status}" = 200

test "$(docker exec "${provisioned_name}" stat --format='%a' /data/bearer_token)" = 600
test "$(docker exec "${provisioned_name}" \
  sh -c 'tr -d "\n" </data/bearer_token | wc -c')" -ge 32

# Read through the file rather than through an argument, so the generated
# secret never appears in a command line.
docker exec "${provisioned_name}" sh -c 'curl --fail --silent \
  --header "Authorization: Bearer $(cat /data/bearer_token)" \
  http://127.0.0.1:8099/info' \
  | jq --exit-status '.service_name == "growspace_manager_vision"' >/dev/null

test "$(docker exec "${provisioned_name}" curl --silent --output /dev/null \
  --write-out '%{http_code}' --header 'Authorization: Bearer not-the-minted-token' \
  http://127.0.0.1:8099/info)" = 401

minted="$(docker exec "${provisioned_name}" sha256sum /data/bearer_token)"
docker restart "${provisioned_name}" >/dev/null
for _attempt in $(seq 1 100); do
  status="$(docker exec "${provisioned_name}" curl --silent --output /dev/null \
    --write-out '%{http_code}' http://127.0.0.1:8099/health || true)"
  [[ "${status}" == 200 ]] && break
  sleep 0.2
done
test "${status}" = 200
test "$(docker exec "${provisioned_name}" sha256sum /data/bearer_token)" = "${minted}"
docker exec "${provisioned_name}" sh -c 'curl --fail --silent \
  --header "Authorization: Bearer $(cat /data/bearer_token)" \
  http://127.0.0.1:8099/info' >/dev/null

printf 'architecture=%s network=none analyze_seconds=%s memory=%s provisioned=reused\n' \
  "${expected_arch}" "${analyze_metrics}" "${memory}"
