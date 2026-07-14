"""Pytest configuration shared by the test suite.

Exposes the path to the googlesearch-mcp executable built from the installed
editable package so the stdio-protocol tests can spawn the real server.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def server_executable() -> list[str]:
    """Command to launch the googlesearch-mcp server over stdio.

    Uses the installed console script when available, falling back to
    `python -m googlesearch_mcp`. The stdio protocol is identical in both cases.
    """
    venv_script = REPO_ROOT / ".venv" / "bin" / "googlesearch-mcp"
    if venv_script.exists():
        return [str(venv_script)]
    return ["python", "-m", "googlesearch_mcp"]


@pytest.fixture
def make_env(monkeypatch):
    """Return a copy of the environment guaranteed to be subprocess-friendly."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    return env
