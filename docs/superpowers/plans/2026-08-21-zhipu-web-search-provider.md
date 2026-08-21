# Zhipu WebSearch Prime Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Zhipu Coding Plan WebSearch Prime as a managed SearchOne provider and selectable SearXNG channel without changing AgentOne.

**Architecture:** A synchronous MCP adapter owns each Streamable HTTP session and is shared by the provider connection probe and an offline SearXNG engine. The engine is named `zhipu`, resolves the encrypted `ZHIPU_CODING_PLAN_API_KEY`, and maps MCP search rows into SearchOne's existing result envelope.

**Tech Stack:** Python 3.11+, httpx, MCP JSON-RPC over Streamable HTTP/SSE, SearXNG offline engine API, Flask, SQLite, unittest, Docker Compose

---

### Task 1: MCP Transport Adapter

**Files:**
- Create: `searchone_control/zhipu_mcp.py`
- Modify: `tests/unit/test_searchone_control.py`

- [ ] **Step 1: Write failing MCP adapter tests**

Add tests using `httpx.MockTransport` that require `initialize`, the
`Mcp-Session-Id` header, `notifications/initialized`, `tools/list`,
`tools/call`, nested JSON decoding, JSON-RPC error handling, MCP `isError`
handling, and best-effort `DELETE` cleanup. Use only fake credentials and
public sample results.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_searchone_control.ZhipuMcpTest
```

Expected: import failure because `searchone_control.zhipu_mcp` does not exist.

- [ ] **Step 3: Implement the minimal adapter**

Create these public operations:

```python
def probe(client: httpx.Client, api_key: str) -> None: ...

def search(
    client: httpx.Client,
    api_key: str,
    query: str,
    *,
    content_size: str = "medium",
) -> list[dict[str, object]]: ...
```

Use private helpers for MCP POST requests, SSE/JSON decoding, session
initialization, tool validation, nested JSON decoding, and cleanup. Never log
authorization headers, session IDs, or raw response bodies.

- [ ] **Step 4: Run the focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_searchone_control.ZhipuMcpTest
```

Expected: PASS.

### Task 2: Managed Provider And Connection Test

**Files:**
- Modify: `searchone_control/db.py`
- Modify: `searchone_control/providers.py`
- Modify: `tests/unit/test_searchone_control.py`

- [ ] **Step 1: Write failing provider tests**

Assert that `zhipu` is seeded with display name `智谱 WebSearch Prime` and env
name `ZHIPU_CODING_PLAN_API_KEY`, encrypted storage round-trips, and
`test_provider("zhipu")` calls the MCP probe through the existing
channel-aware client.

- [ ] **Step 2: Run the focused provider tests and verify RED**

Expected: missing provider and missing probe invocation failures.

- [ ] **Step 3: Add the provider and probe branch**

Add:

```python
("zhipu", "智谱 WebSearch Prime", "ZHIPU_CODING_PLAN_API_KEY")
```

For `zhipu`, the admin test must call `zhipu_mcp.probe(client, key)` and report
HTTP 200 through the existing healthy/failed status fields. Other providers
retain their current request and validation flow.

- [ ] **Step 4: Run the provider tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_searchone_control.SearchOneControlTest
```

Expected: PASS.

### Task 3: Offline SearXNG Engine

**Files:**
- Create: `searx/engines/zhipu_web_search.py`
- Modify: `tests/unit/test_engine_searchone.py`

- [ ] **Step 1: Write failing engine tests**

Import `zhipu_web_search` and assert that it declares `engine_type = "offline"`,
resolves `ZHIPU_CODING_PLAN_API_KEY`, calls the MCP adapter with channel
`zhipu`, maps `title`, `link`, and `content`, and skips malformed rows.

- [ ] **Step 2: Run the focused engine tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_engine_searchone.ZhipuEngineTests
```

Expected: import failure because the engine module does not exist.

- [ ] **Step 3: Implement the engine**

The engine must expose:

```python
engine_type = "offline"
categories = ["general"]
paging = False
api_key = ""

def search(query: str, params: "RequestParams") -> EngineResults: ...
```

Resolve the managed key, create `_client("zhipu")`, call the MCP adapter, and
produce `MainResult` objects. Do not modify existing online engine behavior.

- [ ] **Step 4: Run the engine tests and verify GREEN**

Expected: PASS.

### Task 4: Deployment Configuration And Additive Migration

**Files:**
- Modify: `config/searchone/settings.yml`
- Modify: `config/searchone/.env.example`
- Modify: `config/searchone/README.md`
- Modify: `container/.env.example`
- Modify: `container/docker-compose.yml`
- Modify: `container/entrypoint.sh`
- Modify: `tests/unit/test_searchone_control.py`

- [ ] **Step 1: Write failing deployment guards**

Assert the disabled `zhipu` engine, shortcut `zp`, module
`zhipu_web_search`, Compose passthrough, both environment examples, and
idempotent migration into an existing customized settings file.

- [ ] **Step 2: Run deployment guards and verify RED**

Expected: missing engine and environment failures.

- [ ] **Step 3: Add configuration and migration wiring**

Add the engine YAML and `ZHIPU_CODING_PLAN_API_KEY=` examples. Preserve the
existing image expression and volumes. Update `entrypoint.sh` to run the
existing additive migration for `minimax` and `zhipu`.

- [ ] **Step 4: Run deployment guards and verify GREEN**

Expected: PASS with existing custom engine settings unchanged.

### Task 5: Upstream Protection And Operator Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `UPSTREAM_SYNC.md`
- Modify: `config/searchone/README.md`

- [ ] **Step 1: Add SearchOne-only paths**

Protect `searchone_control/zhipu_mcp.py` and
`searx/engines/zhipu_web_search.py` from routine upstream synchronization.

- [ ] **Step 2: Document configuration**

Document the Coding Plan-only endpoint, environment variable, admin provider
flow, and the `zhipu` client-key channel. Do not include a real credential.

- [ ] **Step 3: Check documentation diff**

```powershell
git diff --check
```

Expected: no whitespace errors or secret values.

### Task 6: Verification And Delivery

**Files:** Verify only.

- [ ] **Step 1: Run required Python checks**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_searchone_control tests.unit.test_engine_searchone
.\.venv\Scripts\python.exe -m pylint searchone_control
```

- [ ] **Step 2: Validate shell and Compose**

```sh
sh -n container/entrypoint.sh
docker compose --env-file container/.env.example -f container/docker-compose.yml config --quiet
```

- [ ] **Step 3: Build and smoke-test the unchanged image name**

```sh
docker build --file container/dist.dockerfile \
  --build-arg VERSION=local-test \
  --build-arg VCS_URL=https://github.com/foxtwobao/searchone \
  --build-arg VCS_BRANCH=feature/zhipu-web-search \
  --tag foxtwobao/searchone:local-test .
docker run --detach --name searchone-zhipu-smoke \
  --publish 127.0.0.1:18888:8888 foxtwobao/searchone:local-test
curl --fail http://127.0.0.1:18888/healthz
docker rm --force searchone-zhipu-smoke
```

- [ ] **Step 4: Perform final repository checks**

```powershell
git diff --check
git status --short
git log --oneline origin/master..HEAD
```

- [ ] **Step 5: Commit, push, and open a Chinese pull request**

The PR summary must state that AgentOne does not change, existing client keys
are not modified automatically, the image name remains unchanged, and the
credential used for manual probing was not committed.

## Completion Status

Implementation and focused verification completed on 2026-08-21:

- 26 SearchOne control-plane tests passed.
- 16 SearchOne engine tests passed with a process-local Windows compatibility
  shim for SearXNG's Linux-only `pwd` import.
- Pylint, `git diff --check`, shell syntax, Compose configuration, and a
  credential-pattern scan passed.
- Image build and `/healthz` smoke testing remain unverified because the local
  Docker Desktop daemon was unavailable. No Runtime E2E gate was requested.
