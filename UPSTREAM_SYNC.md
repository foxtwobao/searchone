# Upstream synchronization policy

SearchOne periodically incorporates changes from `searxng/searxng`. Routine
upstream synchronization must preserve the SearchOne control plane, container
runtime, deployment defaults, and release workflow.

Agent-facing operational instructions are maintained in `AGENTS.md`. Keep the
protected-file lists in both documents synchronized.

## Protected files

Do not replace these files with their upstream versions during a normal sync:

- `.dockerignore`
- `AGENTS.md`
- `README.rst`
- `UPSTREAM_SYNC.md`
- `container/.env.example`
- `container/builder.dockerfile`
- `container/dist.dockerfile`
- `container/docker-compose.yml`
- `container/entrypoint.sh`
- `config/searchone/README.md`
- `.github/workflows/searchone-container.yml`

SearchOne-only paths that do not exist upstream must also be retained:

- `manage-searchone`
- `requirements-searchone.txt`
- `searchone_control/`
- `searchone_control/zhipu_mcp.py`
- `config/searchone/`
- `searx/engines/_searchone_api.py`
- `searx/engines/tavily.py`
- `searx/engines/exa.py`
- `searx/engines/metaso.py`
- `searx/engines/minimax.py`
- `searx/engines/zhipu_web_search.py`
- `searx/engines/tender.py`
- `searx/engines/zhihu.py`
- `tests/unit/test_searchone_control.py`
- `tests/unit/test_engine_searchone.py`

## Exception process

Modify a protected file from upstream only when an upstream security fix,
container base-image change, build-system change, or runtime compatibility fix
requires it. In that case:

1. Merge the upstream change manually instead of replacing the whole file.
2. Preserve the SearchOne entrypoint, port, volumes, dependencies, and image
   publishing behavior.
3. Rebuild the image and run the container health check.
4. Update this document when the protected file set or policy changes.
