"""End-to-end protocol tests against the installed googlesearch-mcp server over stdio.

These tests spawn the real `googlesearch-mcp` executable and speak JSON-RPC over its
stdin/stdout to confirm the transport is genuinely stdio and the MCP lifecycle
(initialize -> notifications/initialized -> tools/list -> tools/call) works.
"""

from __future__ import annotations

import os

import pytest

from tests.stdio_client import StdioMCPClient


@pytest.fixture
def client(server_executable, make_env):
    c = StdioMCPClient(server_executable, make_env, timeout=20)
    yield c
    c.close()


@pytest.fixture
def fake_env(make_env):
    """Env pointing the subprocess at the built-in fake search backend."""
    env = dict(make_env)
    env["GOOGLESEARCH_MCP_BACKEND"] = "fake"
    return env


@pytest.fixture
def fake_client(server_executable, fake_env):
    c = StdioMCPClient(server_executable, fake_env, timeout=20)
    yield c
    c.close()


def test_initialize_over_stdio(client):
    init = client.initialize()
    assert init["jsonrpc"] == "2.0"
    assert init["id"] == 1
    result = init["result"]
    assert result["serverInfo"]["name"] == "search"
    assert "tools" in result["capabilities"]
    # stdio servers do not advertise an HTTP transport capability.
    assert "http" not in result["capabilities"]
    assert "streamableHttp" not in result["capabilities"]


def test_search_tool_is_registered(client):
    client.initialize()
    tools = client.list_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "search"
    assert "Search Google" in tool["description"]
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    assert "query" in schema["required"]
    props = schema["properties"]
    assert set(props) == {"query", "num_results", "lang", "unique", "safe"}
    assert props["query"]["type"] == "string"
    assert props["num_results"]["default"] == 10
    assert props["lang"]["default"] == "en"
    assert props["unique"]["default"] is False
    assert props["safe"]["default"] == "active"


def test_missing_required_query_surfaces_iserror(client):
    client.initialize()
    resp = client.call_tool("search", {})
    assert resp["jsonrpc"] == "2.0"
    # Missing required args are surfaced by FastMCP as a tool result with
    # isError=true (a stringified pydantic validation message), not as a
    # JSON-RPC-level error. This matches how MCP clients learn tool failures.
    result = resp["result"]
    assert result.get("isError") is True
    assert "query" in result["content"][0]["text"]
    assert "Field required" in result["content"][0]["text"]


def test_empty_query_surfaces_iserror(client):
    client.initialize()
    # query present but blank violates our in-tool validation -> ValueError,
    # which FastMCP wraps into an isError tool result.
    resp = client.call_tool("search", {"query": "   "})
    result = resp["result"]
    assert result.get("isError") is True
    assert "query must be a non-empty string" in result["content"][0]["text"]


def test_non_positive_num_results_surfaces_iserror(client):
    client.initialize()
    resp = client.call_tool("search", {"query": "anything", "num_results": 0})
    result = resp["result"]
    assert result.get("isError") is True
    assert "num_results must be a positive integer" in result["content"][0]["text"]


def test_successful_search_over_stdio_with_fake_backend(fake_client):
    """Full happy path: initialize -> tools/call -> structured JSON results.

    Uses the built-in fake backend (GOOGLESEARCH_MCP_BACKEND=fake) so it is fully
    deterministic and exercises the real stdio framing + FastMCP tool dispatch
    + output schema serialization without hitting Google.
    """
    fake_client.initialize()
    resp = fake_client.call_tool(
        "search",
        {"query": "hello world", "num_results": 2},
    )
    result = resp["result"]
    assert result.get("isError") is False
    # FastMCP returns both structuredContent (preference) and content blocks.
    assert "structuredContent" in result or result.get("content")
    items = StdioMCPClient.extract_items(result)
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"index", "title", "url", "description"}
    assert first["index"] == 1
    assert "hello world" in first["title"]
    assert first["url"].startswith("https://example.test/")
    assert first["description"]


def test_search_option_passthrough_over_stdio(fake_client):
    """lang/unique/safe survive the stdio round trip and reach the tool."""
    fake_client.initialize()
    resp = fake_client.call_tool(
        "search",
        {"query": "test", "lang": "fr", "unique": True, "safe": ""},
    )
    result = resp["result"]
    assert result.get("isError") is False
    items = StdioMCPClient.extract_items(result)
    assert len(items) >= 1
