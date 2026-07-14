"""googlesearch-mcp: a Model Context Protocol server that exposes Google search as a tool.

It uses the `googlesearch-python` library (https://github.com/Nv7-GitHub/googlesearch)
which scrapes Google and requires no API key.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("googlesearch-mcp")
except PackageNotFoundError:  # not installed as a package (e.g. running from source)
    try:
        # Backwards-compatible lookup retained so older installs keep working.
        __version__ = version("search-mcp")
    except PackageNotFoundError:
        __version__ = "0.0.0+local"

__all__ = ["__version__"]
