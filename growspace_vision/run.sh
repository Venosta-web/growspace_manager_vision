#!/usr/bin/with-contenv bashio

set -euo pipefail

if [[ -z "${GROWSPACE_VISION_TOKEN:-}" ]]; then
  GROWSPACE_VISION_TOKEN="$(bashio::config access_token)"
  export GROWSPACE_VISION_TOKEN
fi

exec /opt/growspace-vision/venv/bin/python -m growspace_vision
