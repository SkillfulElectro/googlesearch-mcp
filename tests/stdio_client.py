"""A minimal JSON-RPC client that drives the googlesearch-mcp server over stdio.

This is what MCP clients (Claude Desktop, etc.) effectively do: launch the
server as a subprocess, speak newline-delimited JSON-RPC messages over its
stdin/stdout, verify the transport really is stdio, and read responses back.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any


class StdioMCPClient:
    """Bidirectional stdio JSON-RPC client for the MCP server under test."""

    def __init__(self, cmd: list[str], env: dict[str, str], timeout: float = 15.0):
        # bufsize=0 with text=False yields an unbuffered FileIO on Python 3.14
        # which lacks read1(). Use the default (buffered binary) instead and
        # rely on line-buffered framed JSON messages via newlines.
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.timeout = timeout

    def _send(self, message: dict[str, Any]) -> None:
        data = (json.dumps(message) + "\n").encode()
        assert self.process.stdin is not None
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        assert self.process.stdout is not None
        # readline() blocks until a newline or EOF; we rely on the server
        # framing each JSON-RPC message on its own line, which stdio MCP does.
        # To honour the timeout we poll for the process producing output first.
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                # EOF — server closed stdout. Surface stderr for debugging.
                err = self.process.stderr.read() if self.process.stderr else b""
                raise AssertionError(
                    f"server closed stdout. stderr={err.decode('utf-8','replace')[:2000]}"
                )
            if not line.strip():
                continue
            return json.loads(line.decode())
        raise AssertionError("timed out waiting for response")

    def request(self, method: str, params: dict[str, Any] | None = None, *, id: int) -> dict[str, Any]:
        self._send({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})
        return self._read_message()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self, client_name: str = "test-client", client_version: str = "0.1.0") -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": client_version},
            },
            id=1,
        )
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        return self.request("tools/list", id=2).get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any], *, id: int = 3) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments}, id=id)

    def close(self) -> None:
        try:
            self.process.terminate()
        except Exception:
            pass
        try:
            self.process.wait(timeout=2)
        except Exception:
            self.process.kill()

    @staticmethod
    def extract_items(result: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract the list of result objects from a `tools/call` result.

        FastMCP serializes a `-> list[dict]` tool return in two ways:
          - structuredContent.result: the full list (preferred, structured)
          - content: a list of text items, each a JSON-stringified dict

        This helper prefers structuredContent and falls back to parsing every
        text item in content, so tests work regardless of which is present.
        """
        items: list[dict[str, Any]] = []
        sc = result.get("structuredContent")
        if isinstance(sc, dict) and isinstance(sc.get("result"), list):
            return list(sc["result"])
        for block in result.get("content", []) or []:
            if block.get("type") != "text":
                continue
            try:
                parsed = json.loads(block["text"])
            except (json.JSONDecodeError, KeyError):
                continue
            if isinstance(parsed, list):
                items.extend(parsed)
            elif isinstance(parsed, dict):
                items.append(parsed)
        return items
