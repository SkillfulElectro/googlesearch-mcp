# googlesearch-mcp

> deprecated , A New tool will emerge !

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes **Google Search** as a tool.

It uses the [`googlesearch-python`](https://github.com/Nv7-GitHub/googlesearch) library, which scrapes Google directly — **no API key, no billing, no setup**.

## Features

- 🔍 Google search exposed as a single MCP tool.
- 📋 Returns title, URL and description for each result.
- 🌐 Configurable language, result count, deduplication and safe-search.
- 🚫 No API key required.
- 🖥️ Runs over stdio — works out of the box with Claude Desktop and other MCP clients.

## Installation

No build step is required for the end user. Choose one of the configs below and
paste it into your MCP client's config file. The first invocation downloads the
package automatically (just like `npx -y`).

### Quick start — paste into your MCP client config

**Option A: `uvx` (recommended — Python's `npx` equivalent, no install)**

For Claude Desktop's `claude_desktop_config.json`, VS Code / Kilo `mcp.json`, etc.:

```json
{
  "mcpServers": {
    "search": {
      "command": "uvx",
      "args": ["googlesearch-mcp"]
    }
  }
}
```

> Requires [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux).
> `uvx` runs the latest published version straight from PyPI with zero install.

**Option B: from a git repo (no PyPI publish needed)**

```json
{
  "mcpServers": {
    "search": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SkillfulElectro/googlesearch-mcp", "googlesearch-mcp"]
    }
  }
}
```

**Option C: `pipx run` (PyPI, no install)**

```json
{
  "mcpServers": {
    "search": {
      "command": "pipx",
      "args": ["run", "googlesearch-mcp"]
    }
  }
}
```

**Option D: from source (after `pip install .` or `uv pip install .`)**

```json
{
  "mcpServers": {
    "search": {
      "command": "googlesearch-mcp"
    }
  }
}
```

If your client cannot find `googlesearch-mcp` on `PATH`, point it at the module form:

```json
{
  "mcpServers": {
    "search": {
      "command": "python",
      "args": ["-m", "googlesearch_mcp"]
    }
  }
}
```

### From source (this repo)

```bash
uv pip install .          # or: pip install .
googlesearch-mcp          # now on your PATH
```

## Tool: `search`

Search Google and return a list of web results.

| Parameter      | Type    | Default   | Description                                  |
|----------------|---------|-----------|----------------------------------------------|
| `query`        | string  | —         | The search query (required).                 |
| `num_results`  | int     | `10`      | Number of results to return.                 |
| `lang`         | string  | `"en"`    | Language code, e.g. `en`, `fr`, `de`.        |
| `unique`       | bool    | `false`   | Deduplicate result URLs.                     |
| `safe`         | string  | `"active"`| `"active"` enables safe search, `""` disables. |

Each result is an object:

```json
{
  "index": 1,
  "title": "Example Title",
  "url": "https://example.com",
  "description": "Snippet of the page…"
}
```

## Development

```bash
pip install -e .
mcp run googlesearch_mcp.server:app
```

Inspect the server with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx -y @modelcontextprotocol/inspector googlesearch-mcp
```

## Notes

- `googlesearch-python` works by scraping Google. Heavy use may trigger rate limits or CAPTCHAs. If you need a reliable production search backend, consider a paid API (e.g. SerpApi).
- The server runs on the **stdio** transport by default, which is what MCP clients expect.

## Publishing a release

Releases are automated via GitHub Actions (`.github/workflows/publish.yml`):

1. Bump `version` in `pyproject.toml` (e.g. `0.1.1`).
2. Commit and create a Git tag matching the version: `git tag v0.1.1 && git push --tags`.
3. In GitHub, publish a **Release** from that tag (or push the tag manually).
4. The `publish` workflow builds the wheel + sdist and uploads to PyPI using
   **Trusted Publishing** (OIDC) — no PyPI token needed in secrets.

One-time setup for trusted publishing (see
<https://docs.pypi.org/trusted-publishers>):

- Create the project on PyPI first (or claim `googlesearch-mcp`).
- Add a publisher: environment `release`, repo `SkillfulElectro/googlesearch-mcp`,
  workflow filename `publish.yml`.
- In the GitHub repo, create the `release` environment and add `id-token: write`
  permission — already set in the workflow below.

If you prefer a PyPI API token instead of trusted publishing, add a secret
`PYPI_API_TOKEN` and swap the publish job to use `password: ${{ secrets.PYPI_API_TOKEN }}`.
