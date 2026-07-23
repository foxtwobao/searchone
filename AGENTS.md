# SearchOne repository instructions

These instructions apply to the entire repository. They are intended for Codex
and other coding agents working on SearchOne.

## Project runtime

SearchOne extends SearXNG with `searchone_control/`, managed API keys, encrypted
provider credentials, a shared proxy pool, and additional search engines. The
search UI, JSON API, and administration console run in one process and use one
HTTP port.

Local development:

```sh
cp config/searchone/.env.example config/searchone/.env
./manage-searchone run
```

The local service listens on port `8888` by default. Do not introduce a second
web server or a separate administration port.

## Docker Compose deployment

Initial deployment:

```sh
cd container
cp .env.example .env
mkdir -p core-config
docker compose up -d
docker compose logs searchone
```

Health and status checks:

```sh
docker compose ps
curl --fail http://127.0.0.1:8888/healthz
```

Upgrade an existing deployment:

```sh
cd container
docker compose pull
docker compose up -d
```

Stop the deployment without deleting persistent data:

```sh
cd container
docker compose down
```

Do not use `docker compose down --volumes` for a real deployment unless the
user explicitly requests permanent deletion of the database and runtime keys.

Persistent state:

- `container/core-config/` stores SearXNG settings.
- `searchone-data` stores `searchone.db` and `runtime-secrets.env`.
- `core-data` stores SearXNG cache data.
- `valkey-data` stores Valkey data.

The published image is `docker.io/foxtwobao/searchone`. The GitHub workflow
publishes `latest` and `sha-<12 character commit>` tags after changes to
`main` or `master`.

Container builds must use a generic Python/Linux base image. Do not add a
dependency on `searxng/base:*` or `searxng/searxng:*`; all SearXNG application
code must be copied from this repository.

## Local image build

Build the same self-contained image used by GitHub Actions:

```sh
docker build \
  --file container/dist.dockerfile \
  --build-arg VERSION=local \
  --build-arg VCS_URL=https://github.com/foxtwobao/searchone \
  --build-arg VCS_BRANCH="$(git branch --show-current)" \
  --tag foxtwobao/searchone:local \
  .
```

Smoke test it on a non-production host port:

```sh
docker run --detach --name searchone-smoke \
  --publish 127.0.0.1:18888:8888 \
  foxtwobao/searchone:local
```

Then check `http://127.0.0.1:18888/healthz` and remove the test container:

```sh
curl --fail http://127.0.0.1:18888/healthz
docker rm --force searchone-smoke
```

## Upstream synchronization protection

SearchOne tracks `searxng/searxng`, but routine upstream synchronization must
not overwrite the files below. Preserve the SearchOne version and manually
merge upstream changes only when a security, base-image, build-system, or
runtime compatibility change requires it.

Protected files:

- `AGENTS.md`
- `.dockerignore`
- `README.rst`
- `UPSTREAM_SYNC.md`
- `container/.env.example`
- `container/builder.dockerfile`
- `container/dist.dockerfile`
- `container/docker-compose.yml`
- `container/entrypoint.sh`
- `config/searchone/README.md`
- `.github/workflows/searchone-container.yml`

SearchOne-only paths that must always be retained:

- `manage-searchone`
- `requirements-searchone.txt`
- `searchone_control/`
- `config/searchone/`
- `searx/engines/_searchone_api.py`
- `searx/engines/tavily.py`
- `searx/engines/exa.py`
- `searx/engines/metaso.py`
- `searx/engines/tender.py`
- `searx/engines/zhihu.py`
- `tests/unit/test_searchone_control.py`
- `tests/unit/test_engine_searchone.py`

When upstream changes a protected file:

1. Inspect the upstream diff instead of replacing the whole file.
2. Preserve the SearchOne entrypoint, port `8888`, persistent volumes,
   additional dependencies, and Docker Hub publishing behavior.
3. Rebuild and smoke-test the container after the merge.
4. Update this file and `UPSTREAM_SYNC.md` if the protected set changes.

## Required verification

For Python or control-plane changes:

```sh
./manage pyenv.cmd python -m unittest \
  tests.unit.test_searchone_control tests.unit.test_engine_searchone
./manage pyenv.cmd python -m pylint searchone_control
```

For container changes:

```sh
sh -n container/entrypoint.sh
docker compose --env-file container/.env.example \
  -f container/docker-compose.yml config --quiet
docker build --file container/dist.dockerfile \
  --build-arg VERSION=local-test \
  --tag foxtwobao/searchone:local-test .
```

Run a real container or Compose health check before claiming container changes
work. Do not rely only on YAML or Dockerfile parsing.

## Secrets and generated data

Never commit or expose values from:

- `config/searchone/.env`
- `config/searchone/runtime-secrets.env`
- `config/searchone/data/`
- `container/.env`

Do not print administrator passwords, client API keys, provider credentials,
or proxy passwords in final responses, tests, screenshots, or CI logs.
