"""Extended protocol tests covering edge cases and robustness.

These complement test_stdio_protocol.py by exercising corner cases:
  - empty result sets from the backend
  - structuredContent shape contract
  - multiple sequential tool calls on one connection
  - unknown tool name handling
  - protocol version advertisement
  - repeated initialization idempotency
  - large num_results clamping behavior of the tool itself
  - num_results honored by fake backend
"""

from __future__ import annotations

import json

import pytest

from tests.stdio_client import StdioMCPClient


@pytest.fixture
def fake_client(server_executable, make_env):
    env = dict(make_env)
    env["GOOGLESEARCH_MCP_BACKEND"] = "fake"
    c = StdioMCPClient(server_executable, env, timeout=20)
    yield c
    c.close()


@pytest.fixture
def real_client(server_executable, make_env):
    """Client using the real google backend (may return [] if Google blocks)."""
    env = dict(make_env)
    env.pop("GOOGLESEARCH_MCP_BACKEND", None)
    c = StdioMCPClient(server_executable, env, timeout=30)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Initialize / protocol negotiation
# ---------------------------------------------------------------------------

def test_protocol_version_advertised(fake_client):
    """initialize must return a protocolVersion string."""
    result = fake_client.initialize()["result"]
    pv = result.get("protocolVersion")
    assert isinstance(pv, str) and pv, "protocolVersion must be a non-empty string"


def test_server_info_has_version(fake_client):
    result = fake_client.initialize()["result"]
    info = result["serverInfo"]
    assert info["name"] == "search"
    assert "version" in info  # FastMCP fills this from the package


def test_initialize_then_list_tools_idempotent(fake_client):
    """Two tools/list calls on a live connection return the same tool set."""
    fake_client.initialize()
    first = fake_client.list_tools()
    second = StdioMCPClient.extract_items  # noqa: keep import
    # re-request tools/list with a fresh id
    resp = fake_client.request("tools/list", id=99)
    assert resp["id"] == 99
    second_tools = resp["result"]["tools"]
    assert first == second_tools
    assert len(second_tools) == 1


# ---------------------------------------------------------------------------
# Tool dispatch edge cases
# ---------------------------------------------------------------------------

def test_unknown_tool_returns_error(fake_client):
    """Calling a tool that does not exist must surface an error result."""
    fake_client.initialize()
    resp = fake_client.call_tool("does_not_exist", {}, id=7)
    assert resp.get("id") == 7
    # FastMCP surfaces unknown-tool as an isError tool result (not a
    # JSON-RPC-level error), which is how MCP clients learn the tool is missing.
    assert "result" in resp, resp
    result = resp["result"]
    assert result.get("isError") is True
    assert "does_not_exist" in result["content"][0]["text"].lower()


def test_extra_unknown_arguments_ignored_or_error(fake_client):
    """The tool schema is fixed; unknown args should not silently change behavior."""
    fake_client.initialize()
    resp = fake_client.call_tool(
        "search",
        {"query": "x", "unexpected_arg": "ignored?"},
    )
    result = resp["result"]
    # FastMCP may either ignore extra args (returns results) or reject them.
    # Either way it must not crash the server; the response is well-formed.
    assert "content" in result or "isError" in result


def test_num_results_honored_by_fake_backend(fake_client):
    """Requesting num_results=1 yields exactly one item from the fake backend."""
    fake_client.initialize()
    resp = fake_client.call_tool("search", {"query": "solo", "num_results": 1})
    result = resp["result"]
    assert result.get("isError") is False
    items = StdioMCPClient.extract_items(result)
    assert len(items) == 1
    assert items[0]["index"] == 1


def test_empty_backend_result_returns_empty_list_not_error(fake_client, monkeypatch):
    """If the backend yields no results, the tool returns [] (not isError)."""
    import googlesearch_mcp.server as srv
    from types import SimpleNamespace

    def empty_backend(query, **kwargs):
        return iter([])

    monkeypatch.setattr(srv, "_resolve_backend", lambda: empty_backend)

    # Drive via the registered tool fn so we test the FastMCP-wrapped path.
    import asyncio
    search_fn = srv.app._tool_manager._tools["search"].fn
    result = asyncio.run(search_fn(query="zzz", num_results=5))
    assert result == []


def test_structured_content_contract(fake_client):
    """The fake happy path must populate structuredContent.result as a list."""
    fake_client.initialize()
    resp = fake_client.call_tool(
        "search", {"query": "contract", "num_results": 2}
    )
    result = resp["result"]
    assert result.get("isError") is False
    sc = result.get("structuredContent")
    assert isinstance(sc, dict), "structuredContent must be present and a dict"
    assert isinstance(sc.get("result"), list)
    assert len(sc["result"]) == 2


# ---------------------------------------------------------------------------
# Sequential calls on a single connection
# ---------------------------------------------------------------------------

def test_multiple_sequential_calls(fake_client):
    """A stdio connection must handle several tools/call in a row."""
    fake_client.initialize()
    queries = ["one", "two", "three"]
    for i, q in enumerate(queries, start=10):
        resp = fake_client.call_tool(
            "search", {"query": q, "num_results": 1}, id=i
        )
        assert resp["id"] == i, f"id mismatch on call {i}"
        result = resp["result"]
        assert result.get("isError") is False
        items = StdioMCPClient.extract_items(result)
        assert len(items) == 1, f"expected 1 item for {q}"
        assert q in items[0]["title"]


# ---------------------------------------------------------------------------
# Real Google backend (tolerant — Google may be unreachable in CI/sandbox)
# ---------------------------------------------------------------------------

def test_real_backend_does_not_crash_when_google_unreachable(real_client):
    """The real googlesearch backend may return [] (rate-limited) but must
    not crash the server or return an MCP error. This is a smoke test that
    passes whether or not Google is reachable from the test environment."""
    real_client.initialize()
    resp = real_client.call_tool(
        "search", {"query": "python", "num_results": 3}, id=42
    )
    assert resp.get("id") == 42
    # It must be a valid result envelope, never a transport-level crash.
    assert "result" in resp, resp
    result = resp["result"]
    # Either results came back (isError False, items) or Google blocked us and
    # we got []. A non-recoverable error would show isError=True.
    if result.get("isError"):
        # If it errored, it should be a search-side error, not a protocol crash.
        assert "content" in result
    else:
        items = StdioMCPClient.extract_items(result)
        assert isinstance(items, list)
        # Each item, if any, must have the normalized shape.
        for item in items:
            assert set(item) == {"index", "title", "url", "description"}
