"""Unit tests for the `search` tool logic and result normalization.

The tool downloads from Google, which we cannot rely on from a CI/datacenter IP
(rate limits / CAPTCHAs). These tests exercise the tool function directly with
the `googlesearch.search` callable monkeypatched, so they are deterministic and
fast while still going through the FastMCP tool typing, dispatch and schema.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from googlesearch_mcp import server

# FastMCP registers decorated functions into the tool manager rather than
# attaching attributes to the original function. `app` is the FastMCP instance
# and `search_fn` is the actual async callable backing the "search" tool.
app = server.app
search_fn = app._tool_manager._tools["search"].fn


class _FakeResults:
    """Yield SearchResult-like objects to mimic googlesearch.search(... advanced=True)."""

    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


def _advanced_result(title, url, description):
    return SimpleNamespace(title=title, url=url, description=description)


@pytest.mark.asyncio
async def test_search_returns_normalized_advanced_results(monkeypatch):
    fake = _FakeResults([
        _advanced_result("Python", "https://python.org", "Python language"),
        _advanced_result("PyPI", "https://pypi.org", "Package index"),
    ])

    def fake_search(query, **kwargs):
        assert query == "python"
        assert kwargs["advanced"] is True
        assert kwargs["num_results"] == 5
        assert kwargs["lang"] == "en"
        return fake

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)

    result = await search_fn(query="python", num_results=5)
    assert result == [
        {"index": 1, "title": "Python", "url": "https://python.org", "description": "Python language"},
        {"index": 2, "title": "PyPI", "url": "https://pypi.org", "description": "Package index"},
    ]


@pytest.mark.asyncio
async def test_search_passes_through_all_options(monkeypatch):
    captured = {}

    def fake_search(query, **kwargs):
        captured.update(kwargs)
        captured["query"] = query
        return _FakeResults([])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)

    await search_fn(
        query="raspberry pi",
        num_results=7,
        lang="fr",
        unique=True,
        safe="",
    )
    assert captured["query"] == "raspberry pi"
    assert captured["num_results"] == 7
    assert captured["lang"] == "fr"
    assert captured["unique"] is True
    # empty safe string -> falsy -> we should NOT pass safe through to the lib.
    assert "safe" not in captured, captured


@pytest.mark.asyncio
async def test_search_passes_active_safe_through(monkeypatch):
    captured = {}

    def fake_search(query, **kwargs):
        captured.update(kwargs)
        return _FakeResults([])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)

    await search_fn(query="x", safe="active")
    assert captured.get("safe") == "active"


@pytest.mark.asyncio
async def test_search_empty_query_raises_without_calling_google(monkeypatch):
    called = {"n": 0}

    def fake_search(query, **kwargs):
        called["n"] += 1
        return _FakeResults([])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)

    with pytest.raises(ValueError, match="query"):
        await search_fn(query="")
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_search_non_positive_num_results_raises(monkeypatch):
    monkeypatch.setattr(server, "_resolve_backend", lambda: (lambda *a, **k: _FakeResults([])))
    with pytest.raises(ValueError, match="num_results"):
        await search_fn(query="x", num_results=-1)


@pytest.mark.asyncio
async def test_search_handles_non_advanced_strings(monkeypatch):
    # Simulate the library returning plain URL strings (advanced=False path).
    def fake_search(query, **kwargs):
        assert kwargs["advanced"] is True
        # Server always uses advanced=True, but normalize the strings anyway:
        return iter(["https://a.example", "https://b.example"])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)
    result = await search_fn(query="whatever")
    assert result == [
        {"index": 1, "url": "https://a.example", "title": "", "description": ""},
        {"index": 2, "url": "https://b.example", "title": "", "description": ""},
    ]


@pytest.mark.asyncio
async def test_search_raises_propagate_as_iserror_via_fastmcp(monkeypatch):
    def boom(query, **kwargs):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(server, "_resolve_backend", lambda: boom)

    # FastMCP catches exceptions raised by tool functions and surfaces them as
    # an isError=true CallToolResult. At the function level the exception
    # propagates, so confirm the raw exception is the one we raised.
    with pytest.raises(RuntimeError, match="429"):
        await search_fn(query="x")


def test_tool_registered_on_app_with_correct_signature():
    tools = {t.name: t for t in server.app._tool_manager._tools.values()}
    assert "search" in tools
    params = tools["search"].parameters
    assert set(params.get("properties", {})) == {
        "query", "num_results", "lang", "unique", "safe",
    }
    assert params["required"] == ["query"]


def test_main_uses_stdio_transport(monkeypatch):
    captured = {}

    def fake_run(transport):
        captured["transport"] = transport

    monkeypatch.setattr(server.app, "run", fake_run)
    server.main()
    assert captured["transport"] == "stdio"


# ---------------------------------------------------------------------------
# _resolve_backend: google (default) and fake modes
# ---------------------------------------------------------------------------

def test_resolve_backend_defaults_to_google(monkeypatch):
    monkeypatch.delenv("GOOGLESEARCH_MCP_BACKEND", raising=False)
    monkeypatch.delenv("SEARCH_MCP_BACKEND", raising=False)
    assert server._resolve_backend() is server.google_search


def test_resolve_backend_google_explicit(monkeypatch):
    monkeypatch.setenv("GOOGLESEARCH_MCP_BACKEND", "google")
    assert server._resolve_backend() is server.google_search


def test_resolve_backend_unknown_falls_back_to_google(monkeypatch):
    """An unknown backend value must NOT silently produce the fake backend."""
    monkeypatch.setenv("GOOGLESEARCH_MCP_BACKEND", "totally-bogus")
    assert server._resolve_backend() is server.google_search


def test_resolve_backend_fake_returns_callable(monkeypatch):
    monkeypatch.setenv("GOOGLESEARCH_MCP_BACKEND", "fake")
    fn = server._resolve_backend()
    assert callable(fn)
    items = list(fn("q", num_results=3))
    assert len(items) == 3
    assert all(hasattr(i, "title") for i in items)


def test_resolve_backend_fake_is_isolated_per_call(monkeypatch):
    """Each call to _resolve_backend() returns a fresh iterable, so results
    are not consumed/ exhausted across calls."""
    monkeypatch.setenv("GOOGLESEARCH_MCP_BACKEND", "fake")
    fn = server._resolve_backend()
    first = list(fn("a", num_results=2))
    second = list(fn("b", num_results=2))
    assert len(first) == 2 and len(second) == 2
    assert "a" in first[0].title
    assert "b" in second[0].title


# ---------------------------------------------------------------------------
# _search_sync: extra normalization edge cases
# ---------------------------------------------------------------------------

def test_search_sync_with_gap_attributes(monkeypatch):
    """Results missing the description attribute still normalize cleanly."""
    from types import SimpleNamespace

    def fake_search(query, **kwargs):
        return iter([
            SimpleNamespace(title="T", url="https://x"),  # no description
            SimpleNamespace(title="U", url="https://y", description="d"),
        ])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)
    out = server._search_sync(
        query="q", num_results=2, lang="en", advanced=True, unique=False, safe=None
    )
    assert out[0]["description"] == ""
    assert out[1]["description"] == "d"


def test_search_sync_indexes_results_starting_at_one(monkeypatch):
    monkeypatch.setattr(
        server, "_resolve_backend",
        lambda: (lambda q, **k: iter([
            __import__("types").SimpleNamespace(title="a", url="https://a", description=""),
            __import__("types").SimpleNamespace(title="b", url="https://b", description=""),
            __import__("types").SimpleNamespace(title="c", url="https://c", description=""),
        ])),
    )
    out = server._search_sync("q", 10, "en", True, False, None)
    assert [r["index"] for r in out] == [1, 2, 3]


def test_search_sync_passes_lang_default_when_none(monkeypatch):
    captured = {}

    def fake_search(query, **kwargs):
        captured.update(kwargs)
        return iter([])

    monkeypatch.setattr(server, "_resolve_backend", lambda: fake_search)
    server._search_sync("q", 5, None, True, False, None)
    assert captured["lang"] == "en"
