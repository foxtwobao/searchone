# MiniMax Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MiniMax TokenPlan as a managed SearchOne provider and SearXNG engine without changing AgentOne or the published image name.

**Architecture:** A dedicated `minimax` engine sends SearchOne queries to MiniMax's TokenPlan endpoint and normalizes `organic` results. The existing control plane stores one encrypted `MINIMAX_API_KEY`; the existing gateway restricts AgentOne client keys to the new engine.

**Tech Stack:** Python 3.11+, SearXNG engine API, Flask, SQLite, httpx, unittest, Docker Compose

---

### Task 1: MiniMax SearXNG Engine

**Files:**
- Create: `searx/engines/minimax.py`
- Modify: `tests/unit/test_engine_searchone.py`

- [ ] **Step 1: Write failing engine tests**

Import `minimax` and add `MiniMaxEngineTests`. Assert the URL, POST method,
`{"q": query}` body, Bearer header, `organic` mapping, date parsing, malformed-row
filtering, HTTP 429 mapping, invalid JSON, and invalid `organic` envelopes:

```python
from searx.engines import exa, metaso, minimax, tavily, tender, zhihu

class MiniMaxEngineTests(SearxTestCase):
    def test_request_and_response(self):
        request_params = params()
        with patch.object(minimax, "api_key", "minimax-key"):
            minimax.request("联网搜索", request_params)
        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["json"], {"q": "联网搜索"})
        self.assertEqual(
            request_params["headers"]["Authorization"], "Bearer minimax-key"
        )
        results = minimax.response(response({"organic": [{
            "title": "MiniMax 结果",
            "link": "https://example.com/minimax",
            "snippet": "搜索摘要",
            "date": "2026-08-08",
        }, {"title": "缺少链接"}]}))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "搜索摘要")
        self.assertEqual(results[0].publishedDate.date().isoformat(), "2026-08-08")

    def test_rate_limit(self):
        with self.assertRaises(SearxEngineTooManyRequestsException):
            minimax.response(response({"error": "rate limited"}, status_code=429))

    def test_invalid_json_and_payload(self):
        invalid_json = response({})
        invalid_json.json.side_effect = ValueError("invalid json")
        with self.assertRaisesRegex(SearxEngineAPIException, "invalid JSON"):
            minimax.response(invalid_json)
        with self.assertRaisesRegex(SearxEngineAPIException, "invalid response"):
            minimax.response(response({"organic": {}}))
```

- [ ] **Step 2: Run the focused test and verify it fails**

```bash
./manage pyenv.cmd python -m unittest tests.unit.test_engine_searchone.MiniMaxEngineTests
```

Expected: import failure because `searx.engines.minimax` does not exist.

- [ ] **Step 3: Implement `searx/engines/minimax.py`**

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with the MiniMax TokenPlan Search API."""

from __future__ import annotations
import typing as t
from searx.engines._searchone_api import parse_datetime, raise_for_api_error, resolve_api_key
from searx.exceptions import SearxEngineAPIException
from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://www.minimaxi.com/",
    "wikidata_id": None,
    "official_api_documentation": "https://platform.minimaxi.com/",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}
categories = ["general"]
paging = False
send_accept_language_header = False
api_key = ""
base_url = "https://api.minimaxi.com/v1/coding_plan/search"

def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "MINIMAX_API_KEY", "MiniMax")
    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = {"q": query}
    params["headers"].update({
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    params["raise_for_httperror"] = False

def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "MiniMax")
    try:
        data = resp.json()
    except (TypeError, ValueError) as exc:
        raise SearxEngineAPIException("MiniMax: invalid JSON response") from exc
    if not isinstance(data, dict) or not isinstance(data.get("organic"), list):
        raise SearxEngineAPIException("MiniMax: invalid response payload")
    results = EngineResults()
    for item in data["organic"]:
        if not isinstance(item, dict):
            continue
        url, title = item.get("link"), item.get("title")
        if not url or not title:
            continue
        results.add(results.types.MainResult(
            url=url,
            title=title,
            content=item.get("snippet") or "",
            publishedDate=parse_datetime(item.get("date")),
        ))
    return results
```

- [ ] **Step 4: Run the focused tests; expected PASS**
- [ ] **Step 5: Commit with `git commit -m "Add MiniMax search engine"`**

### Task 2: Managed Provider Registration And Test

**Files:**
- Modify: `searchone_control/db.py`
- Modify: `searchone_control/providers.py`
- Modify: `tests/unit/test_searchone_control.py`

- [ ] **Step 1: Write failing provider tests**

Import `Mock` and `_request`. Verify that `minimax` is seeded with
`MINIMAX_API_KEY`, encrypted storage round-trips through `get_provider_secret`,
and `_request` calls the MiniMax endpoint exactly:

```python
def test_minimax_provider_is_seeded_and_encrypted(self):
    providers = {item["provider"]: item for item in self.store.list_providers()}
    self.assertEqual(providers["minimax"]["env_name"], "MINIMAX_API_KEY")
    self.store.update_provider("minimax", "minimax-secret", True)
    self.assertEqual(
        self.store.get_provider_secret("MINIMAX_API_KEY"),
        (True, True, "minimax-secret"),
    )

def test_minimax_provider_connection_request(self):
    client, response_mock = Mock(), Mock()
    client.post.return_value = response_mock
    self.assertIs(_request(client, "minimax", "secret"), response_mock)
    client.post.assert_called_once_with(
        "https://api.minimaxi.com/v1/coding_plan/search",
        headers={"Authorization": "Bearer secret"},
        json={"q": "OpenAI"},
    )
```

- [ ] **Step 2: Run these two tests; expected missing provider failures**
- [ ] **Step 3: Add `("minimax", "MiniMax TokenPlan", "MINIMAX_API_KEY")` to `PROVIDERS`**
- [ ] **Step 4: Add this `_request` branch**

```python
if provider == "minimax":
    return client.post(
        "https://api.minimaxi.com/v1/coding_plan/search",
        headers={"Authorization": f"Bearer {key}"},
        json={"q": "OpenAI"},
    )
```

- [ ] **Step 5: Run `./manage pyenv.cmd python -m unittest tests.unit.test_searchone_control`; expected PASS**
- [ ] **Step 6: Commit with `git commit -m "Manage MiniMax provider credentials"`**

### Task 3: Engine And Container Configuration

**Files:**
- Modify: `config/searchone/settings.yml`
- Modify: `config/searchone/.env.example`
- Modify: `container/.env.example`
- Modify: `container/docker-compose.yml`
- Modify: `tests/unit/test_searchone_control.py`

- [ ] **Step 1: Write a failing configuration guard**

Use `yaml.safe_load` to assert a disabled `minimax` engine with shortcut `mm`,
assert Compose passes `MINIMAX_API_KEY`, and assert both environment examples
contain `MINIMAX_API_KEY=`.

- [ ] **Step 2: Run the guard; expected missing-engine failure**
- [ ] **Step 3: Add the engine declaration**

```yaml
  - name: minimax
    engine: minimax
    shortcut: mm
    categories: [general]
    timeout: 20.0
    disabled: true
```

- [ ] **Step 4: Add `MINIMAX_API_KEY=` to both examples and this Compose mapping**

```yaml
      MINIMAX_API_KEY: ${MINIMAX_API_KEY:-}
```

Do not change the existing `docker.io/foxtwobao/searchone:latest` image declaration.

- [ ] **Step 5: Run both required unit modules and Compose validation; expected PASS**

```bash
./manage pyenv.cmd python -m unittest \
  tests.unit.test_searchone_control tests.unit.test_engine_searchone
docker compose --env-file container/.env.example \
  -f container/docker-compose.yml config --quiet
```

- [ ] **Step 6: Commit with `git commit -m "Configure MiniMax provider deployment"`**

### Task 4: Full Verification And Release Readiness

**Files:** Verify only; do not change production secrets or deployment state.

- [ ] **Step 1: Run required Python checks**

```bash
./manage pyenv.cmd python -m unittest \
  tests.unit.test_searchone_control tests.unit.test_engine_searchone
./manage pyenv.cmd python -m pylint searchone_control
```

- [ ] **Step 2: Validate container configuration**

```bash
sh -n container/entrypoint.sh
docker compose --env-file container/.env.example \
  -f container/docker-compose.yml config --quiet
```

- [ ] **Step 3: Build the unchanged image repository locally**

```bash
docker build --file container/dist.dockerfile \
  --build-arg VERSION=local-test \
  --build-arg VCS_URL=https://github.com/foxtwobao/searchone \
  --build-arg VCS_BRANCH=feature/minimax-provider \
  --tag foxtwobao/searchone:local-test .
```

- [ ] **Step 4: Run and remove only the disposable smoke container**

```bash
docker run --detach --name searchone-minimax-smoke \
  --publish 127.0.0.1:18888:8888 foxtwobao/searchone:local-test
curl --fail http://127.0.0.1:18888/healthz
docker rm --force searchone-minimax-smoke
```

- [ ] **Step 5: Run final repository checks**

```bash
git diff --check
git status --short
git log --oneline master..HEAD
```

Expected: all checks pass, the working tree is clean, and the implementation is
ready to push without exposing any real provider or client credentials.
