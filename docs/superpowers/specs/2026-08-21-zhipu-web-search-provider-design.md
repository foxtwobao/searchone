# SearchOne Zhipu WebSearch Prime Provider Design

## Goal

Add Zhipu GLM Coding Plan WebSearch Prime as an independent SearchOne channel.
Existing AgentOne deployments continue to call SearchOne through the current
`generic_json` integration and require no source change or instance
reinitialization.

## Scope

- Store one managed Zhipu Coding Plan credential under
  `ZHIPU_CODING_PLAN_API_KEY`.
- Connect only to the Coding Plan MCP endpoint:
  `https://open.bigmodel.cn/api/mcp/web_search_prime/mcp`.
- Expose a disabled-by-default SearXNG engine named `zhipu` and display the
  provider as `智谱 WebSearch Prime` in the existing administration page.
- Let client keys and proxy rules select `zhipu` through the existing channel
  pickers.
- Add the engine to persisted SearXNG settings during container upgrades
  without replacing operator customizations.

## Non-Goals

- Changes to AgentOne source, environment variable names, or initialized user
  instances.
- Calling Zhipu's ordinary REST search API, which could bill the account
  balance instead of the Coding Plan subscription.
- Multiple Zhipu keys, rotation, weighted provider routing, or failover.
- Changes to existing SearXNG engines or the published image name.

## Protocol Findings

The production MCP endpoint was probed with an ephemeral credential that was
read from memory and never written to the repository. The endpoint uses
Streamable HTTP and returned these capabilities:

- negotiated protocol version: `2024-11-05`;
- server name: `mcp-web-search-prime`;
- tool name: `web_search_prime`;
- required argument: `search_query`;
- optional arguments: `search_domain_filter`, `search_recency_filter`,
  `content_size`, and `location`;
- successful tool content: a JSON string containing another JSON-encoded array
  of rows with `title`, `link`, `content`, and `refer` fields.

The server requires a session created by `initialize`; a direct `tools/call`
without that session fails. Therefore this provider cannot use the existing
single-request online engine adapter.

## Architecture

`searchone_control/zhipu_mcp.py` is a focused synchronous MCP transport adapter.
It accepts an existing `httpx.Client`, performs `initialize`, sends
`notifications/initialized`, calls `web_search_prime`, decodes JSON-RPC/SSE and
the nested result JSON, then terminates the MCP session on a best-effort basis.
The same adapter exposes a lightweight `probe` operation that validates the
tool catalog without running a web search.

`searx/engines/zhipu_web_search.py` is an `offline` SearXNG engine because one
logical search requires multiple upstream HTTP requests. Its `search` function
resolves the hot-reloadable managed credential, obtains the existing
channel-aware SearchOne HTTP client, invokes the MCP adapter, and maps valid
rows to `MainResult` objects. Each search owns its HTTP client and MCP session,
so concurrent requests do not share mutable session state.

The configured engine name is `zhipu`, not `zhipu_web_search`: SearXNG rejects
engine names containing underscores. The module name remains descriptive while
the provider ID, client-key channel value, and proxy channel value stay aligned
as `zhipu`.

## Data Flow

1. AgentOne calls its unchanged web-research endpoint.
2. AgentOne's existing `generic_json` provider calls SearchOne with the current
   SearchOne client key.
3. SearchOne runs every engine allowed by that key, including `zhipu` when it
   is selected.
4. The Zhipu engine resolves `ZHIPU_CODING_PLAN_API_KEY` from encrypted provider
   storage or the environment.
5. The MCP adapter creates a session, invokes `web_search_prime`, parses the
   returned rows, and closes the session.
6. SearchOne merges Zhipu results with results from any other selected channels
   and returns its existing JSON envelope.

## Error Handling

- Missing or disabled credentials retain the existing SearchOne provider-key
  behavior.
- HTTP 401, 402, and 403 map to access denied; HTTP 429 maps to too many
  requests; other HTTP failures map to provider API errors.
- JSON-RPC `error`, MCP `isError`, missing session headers, missing tools, bad
  SSE/JSON, and malformed nested result payloads fail explicitly.
- Individual rows without non-empty string `title` and `link` values are
  skipped. Optional content defaults to an empty string.
- Session cleanup is best effort and never replaces a successful search result
  with a cleanup failure.
- Admin connection tests show concise Chinese failures and never include the
  credential or raw upstream response body.

## Configuration And Upgrade

Register the provider as:

```python
("zhipu", "智谱 WebSearch Prime", "ZHIPU_CODING_PLAN_API_KEY")
```

Register the engine as:

```yaml
- name: zhipu
  engine: zhipu_web_search
  shortcut: zp
  categories: [general]
  timeout: 30.0
  disabled: true
```

The container passes through `ZHIPU_CODING_PLAN_API_KEY`, while operators may
leave it empty and save the real value through `/admin/providers`. The
entrypoint runs the existing additive settings migration for both `minimax`
and `zhipu`. Existing engines and custom settings remain unchanged.

The image remains:

```yaml
image: ${SEARCHONE_IMAGE:-docker.io/foxtwobao/searchone}:${SEARCHONE_VERSION:-latest}
```

No volume is deleted or recreated. Existing SearchOne client keys keep their
current allowed-channel lists until an administrator explicitly selects
`zhipu`.

## Verification

- Unit-test MCP initialization, session headers, notifications, tool calls,
  SSE/JSON parsing, nested result decoding, errors, and cleanup.
- Unit-test engine credential resolution, result mapping, and malformed-row
  filtering.
- Unit-test provider seeding, encrypted credential retrieval, connection probe,
  environment examples, Compose passthrough, and additive settings migration.
- Run the two required SearchOne unit modules and pylint.
- Validate the entrypoint and Compose configuration.
- Build the unchanged image repository and verify `/healthz` in a disposable
  container when Docker Desktop is available.
