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

FROM ${PYTHON_IMAGE} AS dist

ENV HOME="/usr/local/searxng" \
    PATH="/usr/local/searxng/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    SSL_CERT_DIR="/etc/ssl/certs" \
    SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt" \
    __SEARXNG_CONFIG_PATH="/etc/searxng" \
    __SEARXNG_DATA_PATH="/var/cache/searxng" \
    SEARXNG_SETTINGS_PATH="/etc/searxng/settings.yml"

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      ca-certificates \
      gosu \
      libffi8 \
      libxml2 \
      libxslt1.1 \
      tini \
      tzdata; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 977 searxng; \
    useradd --uid 977 --gid 977 --home-dir /usr/local/searxng \
      --shell /usr/sbin/nologin --no-create-home searxng; \
    mkdir -p /usr/local/searxng /etc/searxng /var/cache/searxng /var/lib/searchone; \
    chown -R 977:977 /usr/local/searxng /etc/searxng /var/cache/searxng /var/lib/searchone

WORKDIR /usr/local/searxng

COPY --chown=977:977 --from=builder /usr/local/searxng/.venv/ ./.venv/
COPY --chown=977:977 --from=builder /usr/local/searxng/searx/ ./searx/
COPY --chown=977:977 --from=builder /usr/local/searxng/searchone_control/ ./searchone_control/
COPY --chown=977:977 ./container/ ./
COPY --chown=977:977 ./config/searchone/settings.yml ./settings.template.yml

ARG CREATED="0001-01-01T00:00:00Z"
ARG VERSION="unknown"
ARG VCS_URL="unknown"
ARG VCS_REVISION="unknown"
ARG VCS_BRANCH="unknown"

RUN set -eux; \
    printf '%s\n' \
      '# SPDX-License-Identifier: AGPL-3.0-or-later' \
      '# this file is generated during the SearchOne image build' \
      "VERSION_STRING = \"$VERSION\"" \
      "VERSION_TAG = \"$VERSION\"" \
      "DOCKER_TAG = \"$VERSION\"" \
      "GIT_URL = \"$VCS_URL\"" \
      "GIT_BRANCH = \"$VCS_BRANCH\"" \
      > ./searx/version_frozen.py; \
    chown 977:977 ./searx/version_frozen.py

LABEL org.opencontainers.image.created="$CREATED" \
    org.opencontainers.image.description="SearchOne search gateway and administration plane based on SearXNG." \
    org.opencontainers.image.documentation="https://github.com/foxtwobao/searchone" \
    org.opencontainers.image.licenses="AGPL-3.0-or-later" \
    org.opencontainers.image.revision="$VCS_REVISION" \
    org.opencontainers.image.source="$VCS_URL" \
    org.opencontainers.image.title="SearchOne" \
    org.opencontainers.image.url="https://github.com/foxtwobao/searchone" \
    org.opencontainers.image.version="$VERSION"

ENV __SEARXNG_VERSION="$VERSION" \
    SEARCHONE_DATA_PATH="/var/lib/searchone" \
    SEARCHONE_DATABASE_PATH="/var/lib/searchone/searchone.db" \
    SEARCHONE_RUNTIME_ENV_FILE="/var/lib/searchone/runtime-secrets.env" \
    GRANIAN_PROCESS_NAME="searchone" \
    GRANIAN_INTERFACE="wsgi" \
    GRANIAN_HOST="::" \
    GRANIAN_PORT="8888" \
    GRANIAN_WEBSOCKETS="false" \
    GRANIAN_BLOCKING_THREADS="4" \
    GRANIAN_WORKERS_KILL_TIMEOUT="30s" \
    GRANIAN_BLOCKING_THREADS_IDLE_TIMEOUT="5m"

VOLUME ["/etc/searxng", "/var/cache/searxng", "/var/lib/searchone"]

EXPOSE 8888

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/searxng/entrypoint.sh"]
