"""Synchronous MCP client for Zhipu Coding Plan WebSearch Prime."""

from __future__ import annotations

import json
from typing import Any

import httpx


ENDPOINT = "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
TOOL_NAME = "web_search_prime"
PROTOCOL_VERSION = "2024-11-05"


class ZhipuMcpError(ValueError):
    """Raised when the Zhipu MCP server violates the expected contract."""


class ZhipuMcpHttpError(ZhipuMcpError):
    """Raised when the MCP endpoint returns an unsuccessful HTTP status."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"智谱 MCP 请求失败（HTTP {status_code}）")


def _headers(api_key: str, session_id: str = "") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _raise_http_error(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    raise ZhipuMcpHttpError(status)


def _sse_data(text: str) -> list[str]:
    events: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
        elif not line and current:
            events.append("\n".join(current))
            current = []
    if current:
        events.append("\n".join(current))
    return events


def _response_payload(response: httpx.Response, operation: str) -> dict[str, Any]:
    _raise_http_error(response)
    content_type = response.headers.get("content-type", "").lower()
    candidates = (
        _sse_data(response.text)
        if "text/event-stream" in content_type
        else [response.text]
    )
    for candidate in candidates:
        if not candidate.strip():
            continue
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code", "unknown")
            raise ZhipuMcpError(f"智谱 MCP {operation}失败（错误码 {code}）")
        return payload
    raise ZhipuMcpError(f"智谱 MCP {operation}返回格式无效")


def _post(
    client: httpx.Client,
    api_key: str,
    payload: dict[str, Any],
    operation: str,
    session_id: str = "",
) -> tuple[httpx.Response, dict[str, Any]]:
    response = client.post(
        ENDPOINT,
        headers=_headers(api_key, session_id),
        json=payload,
    )
    return response, _response_payload(response, operation)


def _initialize(client: httpx.Client, api_key: str) -> str:
    response, payload = _post(
        client,
        api_key,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "searchone", "version": "1.0"},
            },
        },
        "初始化",
    )
    if not isinstance(payload.get("result"), dict):
        raise ZhipuMcpError("智谱 MCP 初始化返回格式无效")
    session_id = response.headers.get("mcp-session-id", "").strip()
    if not session_id:
        raise ZhipuMcpError("智谱 MCP 初始化未返回会话标识")
    return session_id


def _notify_initialized(client: httpx.Client, api_key: str, session_id: str) -> None:
    response = client.post(
        ENDPOINT,
        headers=_headers(api_key, session_id),
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
    )
    _raise_http_error(response)


def _close_session(client: httpx.Client, api_key: str, session_id: str) -> None:
    if not session_id:
        return
    try:
        client.delete(ENDPOINT, headers=_headers(api_key, session_id))
    except httpx.HTTPError:
        pass


def _tool_catalog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise ZhipuMcpError("智谱 MCP 工具列表返回格式无效")
    return [item for item in tools if isinstance(item, dict)]


def probe(client: httpx.Client, api_key: str) -> None:
    """Verify that the credential can initialize and list WebSearch Prime."""

    session_id = _initialize(client, api_key)
    try:
        _notify_initialized(client, api_key, session_id)
        _, payload = _post(
            client,
            api_key,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            "工具发现",
            session_id,
        )
        tool = next(
            (item for item in _tool_catalog(payload) if item.get("name") == TOOL_NAME),
            None,
        )
        if tool is None:
            raise ZhipuMcpError("智谱 MCP 未提供 WebSearch Prime 工具")
        schema = tool.get("inputSchema")
        required = schema.get("required", []) if isinstance(schema, dict) else []
        if "search_query" not in required:
            raise ZhipuMcpError("智谱 MCP WebSearch Prime 参数格式无效")
    finally:
        _close_session(client, api_key, session_id)


def _decode_rows(content: Any) -> list[dict[str, object]]:
    value = content
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ZhipuMcpError("智谱 MCP 搜索结果不是有效 JSON") from exc
    if not isinstance(value, list):
        raise ZhipuMcpError("智谱 MCP 搜索结果格式无效")
    return [item for item in value if isinstance(item, dict)]


def search(
    client: httpx.Client,
    api_key: str,
    query: str,
    *,
    content_size: str = "medium",
) -> list[dict[str, object]]:
    """Run one WebSearch Prime tool call and return decoded result rows."""

    session_id = _initialize(client, api_key)
    try:
        _notify_initialized(client, api_key, session_id)
        _, payload = _post(
            client,
            api_key,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": {
                        "search_query": query,
                        "content_size": content_size,
                    },
                },
            },
            "搜索",
            session_id,
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ZhipuMcpError("智谱 MCP 搜索返回格式无效")
        if result.get("isError") is True:
            raise ZhipuMcpError("智谱 MCP 搜索失败")
        content = result.get("content")
        if not isinstance(content, list):
            raise ZhipuMcpError("智谱 MCP 搜索内容格式无效")
        text = next(
            (
                item.get("text")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ),
            None,
        )
        return _decode_rows(text)
    finally:
        _close_session(client, api_key, session_id)
