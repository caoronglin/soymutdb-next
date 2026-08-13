"""End-to-end authentication checks against FastMCP's HTTP transport."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import json

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post_mcp(url: str, authorization: str | None) -> int:
    request = urllib.request.Request(url, data=b"{}", method="POST")
    if authorization is not None:
        request.add_header("Authorization", authorization)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _post_initialize(url: str, token: str | None) -> int:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "healthcheck", "version": "1"},
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.fixture
def mcp_server(monkeypatch):
    token = "transport-test-token"
    monkeypatch.setenv("SOYMUTDB_MCP_API_TOKEN", token)
    port = _free_port()
    env = os.environ.copy()
    process = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            _post_mcp(url, None)
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.05)
    else:
        process.kill()
        pytest.fail("FastMCP HTTP server did not start")
    try:
        yield url, token
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_streamable_http_rejects_missing_empty_wrong_scheme_and_token(mcp_server):
    url, _ = mcp_server
    for authorization in (None, "Bearer ", "Basic transport-test-token", "Bearer wrong"):
        assert _post_mcp(url, authorization) == 401


def test_streamable_http_accepts_correct_bearer(mcp_server):
    url, token = mcp_server
    assert 200 <= _post_initialize(url, token) < 300


def test_initialize_rejects_missing_and_wrong_bearer(mcp_server):
    url, token = mcp_server
    assert _post_initialize(url, None) == 401
    assert _post_initialize(url, f"{token}-wrong") == 401
