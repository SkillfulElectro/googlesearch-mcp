"""MCP server that exposes Google search as a tool.

Run it with the stdio transport (the default for MCP servers used by LLM clients):

    googlesearch-mcp              # installed entry point
    python -m googlesearch_mcp   # if installed
    mcp run googlesearch_mcp.server:app  # via the mcp CLI

Configure it in an MCP-compatible client (Claude Desktop, etc.) with:

    {
      "mcpServers": {
        "search": {
          "command": "googlesearch-mcp"
        }
      }
    }
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Iterable

from googlesearch import search as google_search

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("googlesearch_mcp")

app = FastMCP("search")


def _resolve_backend() -> Callable[..., Iterable[Any]]:
    """Return the search callable the tool should use.

    Defaults to the real `googlesearch.search`. Tests can point stdio-spawned
    subprocesses at a built-in fake backend by setting GOOGLESEARCH_MCP_BACKEND=fake,
    so a successful tool call can be exercised over the real stdio transport
    without depending on Google.
    """
    backend = os.environ.get("GOOGLESEARCH_MCP_BACKEND") or os.environ.get("SEARCH_MCP_BACKEND", "google")
    if backend == "fake":
        def fake_search(query: str, num_results: int = 10, **kwargs: Any) -> Iterable[Any]:
            from types import SimpleNamespace
            n = max(1, int(num_results) if isinstance(num_results, int) else 10)
            return [
                SimpleNamespace(title=f"Result for '{query}' #{i}",
                                url=f"https://example.test/{i}",
                                description="fake description" if i % 2 else "another fake")
                for i in range(1, n + 1)
            ]
        return fake_search
    return google_search


def _search_sync(
    query: str,
    num_results: int,
    lang: str | None,
    advanced: bool,
    unique: bool,
    safe: str | None,
) -> list[dict[str, Any]]:
    """Run a Google search synchronously and normalize the results into dicts."""
    kwargs: dict[str, Any] = {
        "num_results": num_results,
        "advanced": advanced,
        "unique": unique,
        "lang": lang or "en",
    }
    if safe:  # "active" enables safe search; falsy disables it
        kwargs["safe"] = safe

    results = _resolve_backend()(query, **kwargs)

    out: list[dict[str, Any]] = []
    for i, r in enumerate(results, start=1):
        entry: dict[str, Any] = {"index": i}
        # The advanced SearchResult objects expose .url / .title / .description.
        # Plain strings (advanced=False) only have the url; treat them as such.
        # NB: do not use getattr(r, "title", "") for strings — str.title is a
        # method, which would be captured instead of "".
        if advanced and hasattr(r, "url"):
            entry["title"] = getattr(r, "title", "") or ""
            entry["url"] = getattr(r, "url", "") or ""
            entry["description"] = getattr(r, "description", "") or ""
        else:
            entry["url"] = str(r)
            entry["title"] = ""
            entry["description"] = ""
        out.append(entry)
    return out


@app.tool()
async def search(
    query: str,
    num_results: int = 10,
    lang: str = "en",
    unique: bool = False,
    safe: str = "active",
) -> list[dict[str, Any]]:
    """Search Google and return web results. Powered by the `googlesearch-python` library (no API key needed).

    Args:
        query: The search query.
        num_results: How many results to return (default 10).
        lang: Language code for results, e.g. "en", "fr", "de" (default "en").
        unique: Deduplicate result URLs when True (default False).
        safe: Safe-search filter. Use "active" to enable, "" to disable (default "active").

    Returns:
        A list of result objects with keys: index, title, url, description.

    Raises:
        ValueError: If `query` is empty/blank or `num_results` is not positive.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if num_results <= 0:
        raise ValueError("num_results must be a positive integer")

    safe_value = safe if safe else None
    return _search_sync(
        query=query,
        num_results=num_results,
        lang=lang,
        advanced=True,
        unique=unique,
        safe=safe_value,
    )


def main() -> None:
    """Entry point for the `googlesearch-mcp` console script.

    Runs the server on the stdio transport, which is what MCP-compatible LLM
    clients (Claude Desktop, etc.) use to launch and talk to a server process.
    """
    logging.basicConfig(level=logging.INFO)
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
