# SearchOne MiniMax Provider Design

## Goal

Add MiniMax TokenPlan as a first-class SearchOne provider so AgentOne can route
web searches through SearchOne without changing AgentOne code or reinitializing
existing user instances.

## Scope

- Support one managed MiniMax TokenPlan credential.
- Call `POST https://api.minimaxi.com/v1/coding_plan/search` with Bearer
  authentication and JSON body `{"q": query}`.
- Expose MiniMax in the existing provider administration page and connection
  test flow.
- Expose a `minimax` SearXNG engine that can be assigned to SearchOne client
  keys.
- Preserve the current Docker image repository and default tag:
  `docker.io/foxtwobao/searchone:latest`.

## Non-Goals

- Multiple MiniMax keys, rotation, weighted routing, or provider failover.
- Changes to AgentOne source code or managed instance initialization.
- A second proxy service, web server, database migration, or administration
  port.
- Routing AgentOne URL-reading requests through SearchOne.

## Architecture

`searx/engines/minimax.py` implements the MiniMax request and response adapter.
It resolves `MINIMAX_API_KEY` through the existing hot-reloadable provider
credential mechanism, then falls back to the environment variable in the same
way as the other SearchOne API engines.

`searchone_control/db.py` registers the provider as:

```python
("minimax", "MiniMax TokenPlan", "MINIMAX_API_KEY")
```

Database initialization already uses `INSERT OR IGNORE`, so an existing
`searchone-data` volume receives the new provider row on the next application
start without a schema migration or changes to existing credentials and client
keys.

`searchone_control/providers.py` adds a connection test using the same endpoint,
Bearer header, request body, timeout, and shared proxy selection used by the
runtime engine.

`config/searchone/settings.yml` declares the `minimax` engine in the `general`
category with shortcut `mm`, a 20-second timeout, and `disabled: true`. Client
keys can then be restricted to `allowed_engines: ["minimax"]`.

## Data Flow

1. A managed runtime calls the unchanged AgentOne
   `/api/web-research/search` endpoint using its existing instance token.
2. AgentOne's existing `generic_json` provider calls
   `https://search.agentone.work/api/v1/search` with its SearchOne client key.
3. The SearchOne gateway restricts the request to the client key's allowed
   `minimax` engine.
4. The MiniMax engine sends `{"q": query}` to the TokenPlan search endpoint.
5. Each valid `organic` result maps `link`, `title`, `snippet`, and `date` to a
   SearXNG `MainResult` (`url`, `title`, `content`, and `publishedDate`).
6. SearchOne returns its normal JSON result envelope, which AgentOne already
   normalizes through `generic_json`.

## Error Handling

- Missing or disabled credentials use the existing provider error behavior.
- HTTP 429 maps to the existing too-many-requests engine exception.
- HTTP 402 and 403 map to access-denied; other HTTP failures map to the generic
  engine API exception.
- Invalid JSON and malformed top-level payloads fail as provider API errors
  instead of silently returning success.
- Individual result rows without both `link` and `title` are skipped.
- Provider connection-test failures are recorded in the existing status and
  message fields, with the existing 300-character limit.

## Configuration And Deployment

Add `MINIMAX_API_KEY` to both environment examples and pass it through
`container/docker-compose.yml`. Operators may leave it empty and save the real
credential later in `/admin/providers`, where it is encrypted in the existing
database.

The deployment continues to use:

```yaml
image: ${SEARCHONE_IMAGE:-docker.io/foxtwobao/searchone}:${SEARCHONE_VERSION:-latest}
```

Existing `core-config`, `core-data`, `searchone-data`, and `valkey-data` mounts
remain unchanged. The release process pulls and recreates only SearchOne, with
no volume deletion.

After SearchOne verification, create separate SearchOne client keys for
`agentone-zgo-migrated` and `agentone-server`, initially allowing only
`minimax`. Switch `agentone-zgo-migrated` first, observe it, and then switch
`agentone-server`.

## Compatibility And Rollback

Existing AgentOne instances retain `AGENTONE_WEB_RESEARCH_BASE_URL` and
`AGENTONE_WEB_RESEARCH_TOKEN`, so they continue to call the same AgentOne API
and require no reinitialization or container rebuild.

Rollback restores each AgentOne deployment's previous direct MiniMax provider
settings. SearchOne's persisted provider row is additive and does not alter
existing clients or credentials.

Because `latest` is mutable, record the pre-release image digest or retain a
separate rollback tag before publishing the updated `latest` image. The Stack
image name itself remains unchanged.

## Verification

- Unit-test MiniMax request method, URL, Bearer header, body, result mapping,
  date parsing, skipped malformed rows, API errors, and invalid payloads.
- Unit-test provider seeding, encrypted credential retrieval, and the provider
  connection-test request.
- Run the required SearchOne control-plane and engine unit tests.
- Run pylint for `searchone_control`.
- Validate Compose with `container/.env.example`.
- Build `foxtwobao/searchone:local-test`, start a disposable container, and
  verify `/healthz` before publishing.
