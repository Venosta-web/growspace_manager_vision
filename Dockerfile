FROM ghcr.io/home-assistant/base-debian:trixie-2026.08.0@sha256:01e153da2c2579f2cf5010901da7bc31b1dd035921ea46ccaff22e521efa74a7

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/growspace-vision/source

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python3 -m venv /opt/growspace-vision/venv \
    && /opt/growspace-vision/venv/bin/python -m pip install \
        --no-cache-dir \
        .

ENV PATH="/opt/growspace-vision/venv/bin:${PATH}"

EXPOSE 8099

CMD ["/command/with-contenv", "growspace-vision"]
