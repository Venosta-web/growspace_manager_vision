FROM ghcr.io/home-assistant/base-debian:trixie-2026.08.0@sha256:01e153da2c2579f2cf5010901da7bc31b1dd035921ea46ccaff22e521efa74a7

ARG TARGETARCH
ARG SOURCE_DATE_EPOCH=1788134400

COPY .build-inputs/${TARGETARCH}/ /tmp/build-inputs/
COPY packaging/requirements-runtime.txt /tmp/requirements-runtime.txt

RUN test "${TARGETARCH}" = "amd64" -o "${TARGETARCH}" = "arm64" \
    && cd /tmp/build-inputs \
    && jq --raw-output '.artifacts[] | "\(.sha256)  \(.path)"' manifest.json \
        | sha256sum --check --strict \
    && diff --unified \
        <(jq --raw-output '.artifacts[].path' manifest.json | sort) \
        <(find . -type f ! -name manifest.json -printf '%P\n' | sort) \
    && while IFS=$'\t' read -r expected path; do \
        test "$(stat --format='%s' "${path}")" = "${expected}"; \
    done < <(jq --raw-output '.artifacts[] | "\(.size_bytes)\t\(.path)"' manifest.json) \
    && apt-get install --yes --no-install-recommends \
        /tmp/build-inputs/debs/*.deb \
    && python3 -m venv /opt/growspace-vision/venv \
    && /opt/growspace-vision/venv/bin/python -m pip install \
        --disable-pip-version-check \
        --no-index \
        --no-cache-dir \
        --find-links /tmp/build-inputs/wheels \
        --require-hashes \
        --requirement /tmp/requirements-runtime.txt \
    && mkdir -p /opt/growspace-vision/models /opt/growspace-vision/licenses \
    && install -m 0444 /tmp/build-inputs/model/model_int8.onnx \
        /opt/growspace-vision/models/model_int8.onnx \
    && cp -a /tmp/build-inputs/licenses/. /opt/growspace-vision/licenses/ \
    && install -m 0444 /tmp/build-inputs/manifest.json \
        /opt/growspace-vision/build-inputs.json \
    && rm -rf /tmp/build-inputs /tmp/requirements-runtime.txt \
        /root/.cache /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /opt/growspace-vision/source

COPY src ./src
COPY LICENSE README.md packaging/THIRD_PARTY_NOTICES.md ./
COPY scripts/generate-sbom.py /tmp/generate-sbom.py
COPY growspace_vision/run.sh /run.sh

RUN /opt/growspace-vision/venv/bin/python /tmp/generate-sbom.py \
        --arch "${TARGETARCH}" \
        --manifest /opt/growspace-vision/build-inputs.json \
        --output /opt/growspace-vision/sbom.spdx.json \
    && chmod 0555 /run.sh \
    && rm /tmp/generate-sbom.py

ENV PATH="/opt/growspace-vision/venv/bin:${PATH}" \
    PYTHONPATH="/opt/growspace-vision/source/src" \
    GROWSPACE_VISION_MODEL_PATH="/opt/growspace-vision/models/model_int8.onnx" \
    GROWSPACE_VISION_SERVICE_VERSION="1.0.0" \
    ORT_DISABLE_TELEMETRY="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1"

LABEL \
    io.hass.type="app" \
    io.hass.name="Growspace Vision" \
    io.hass.description="Local, stateless image analysis for Growspace Manager" \
    io.hass.url="https://github.com/Venosta-web/growspace_manager_vision" \
    io.hass.version="1.0.0" \
    io.hass.arch="${TARGETARCH}" \
    org.opencontainers.image.title="Home Assistant App: Growspace Vision" \
    org.opencontainers.image.description="Local, stateless image analysis for Growspace Manager" \
    org.opencontainers.image.source="https://github.com/Venosta-web/growspace_manager_vision" \
    org.opencontainers.image.version="1.0.0" \
    org.opencontainers.image.licenses="MIT AND Apache-2.0"

EXPOSE 8099

CMD ["/run.sh"]
