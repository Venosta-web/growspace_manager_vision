#!/usr/bin/with-contenv bashio

set -euo pipefail

# provision.py owns both halves of the credential lifecycle: it resolves or
# mints the Bearer token and announces {host, port, token} to Supervisor. It
# prints the token and nothing else, so a failure here fails the start rather
# than serving an unauthenticated or unreachable service.
GROWSPACE_VISION_TOKEN="$(
  /opt/growspace-vision/venv/bin/python /opt/growspace-vision/provision.py \
    --data-dir /data \
    --port 8099
)"
export GROWSPACE_VISION_TOKEN

exec /opt/growspace-vision/venv/bin/python -m growspace_vision
