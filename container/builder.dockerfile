ARG PYTHON_IMAGE="docker.io/library/python:3.14-slim-bookworm"

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK="1" \
    PIP_NO_CACHE_DIR="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    VIRTUAL_ENV="/usr/local/searxng/.venv"

WORKDIR /usr/local/searxng

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      brotli \
      build-essential \
      libffi-dev \
      libxml2-dev \
      libxslt1-dev \
      zlib1g-dev; \
    rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./requirements-server.txt ./requirements-searchone.txt ./

ARG TIMESTAMP_VENV="0"

RUN set -eux; \
    export SOURCE_DATE_EPOCH="$TIMESTAMP_VENV"; \
    python -m venv "$VIRTUAL_ENV"; \
    "$VIRTUAL_ENV/bin/pip" install \
      --requirement ./requirements.txt \
      --requirement ./requirements-server.txt \
      --requirement ./requirements-searchone.txt; \
    find "$VIRTUAL_ENV/lib" -type f \( -name "*.so" -o -name "*.so.*" \) \
      -exec strip --strip-unneeded {} + || true; \
    find "$VIRTUAL_ENV/lib" -type d -name "__pycache__" -exec rm -rf {} +; \
    find "$VIRTUAL_ENV/lib" -type f -name "*.pyc" -delete; \
    "$VIRTUAL_ENV/bin/python" -m compileall -q -f -j 0 \
      --invalidation-mode=unchecked-hash "$VIRTUAL_ENV/lib/"

COPY --exclude=./searx/version_frozen.py ./searx/ ./searx/
COPY ./searchone_control/ ./searchone_control/

RUN set -eux; \
    "$VIRTUAL_ENV/bin/python" -m compileall -q -f -j 0 \
      --invalidation-mode=unchecked-hash ./searx/ ./searchone_control/; \
    find ./searx/static/ -type f \
      \( -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.svg" \) \
      -exec gzip -9 -k {} + \
      -exec brotli -9 -k {} +; \
    find ./searx/static/ -type f -name "*.gz" -exec gzip --test {} +; \
    find ./searx/static/ -type f -name "*.br" -exec brotli --test {} +
