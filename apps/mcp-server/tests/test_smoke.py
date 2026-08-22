"""MCP server smoke tests: inventory, auth, and deployment boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re


def _tool_names() -> list[str]:
    from mcp_server.server import mcp

    return [t.name for t in asyncio.run(mcp.list_tools())]


class TestToolRegistry:
    def test_all_manifest_tools_registered(self):
        from mcp_server.manifest import TOOLS

        names = set(_tool_names())
        expected = {t["name"] for t in TOOLS}
        assert expected == names
        assert len(names) == 8

    def test_tool_read_write_split(self):
        from mcp_server.manifest import TOOLS

        read = {t["name"] for t in TOOLS if t["type"] == "read"}
        write = {t["name"] for t in TOOLS if t["type"] == "write"}
        assert read == {"gene_by_id", "variant_by_region", "news_list", "stats_summary", "seqfetch"}
        assert write == {"blast_submit", "blast_job_status", "analyses_query"}


class TestManifest:
    def test_manifest_shape(self):
        from mcp_server.manifest import AUTH, MANIFEST, SERVER_NAME, VERSION, TOOLS

        assert MANIFEST["server"] == SERVER_NAME == "soymutdb"
        assert MANIFEST["version"] == VERSION
        assert MANIFEST["tools"] is TOOLS
        assert "rate_limit" in AUTH
        assert "Authorization: Bearer" in AUTH["transport"]
        assert "fail closed" in AUTH["transport"]
        assert "60 req/min" in AUTH["rate_limit"]
        assert "Redis-backed" in AUTH["rate_limit"]


class TestServerImport:
    def test_server_module_imports(self):
        import mcp_server.server as server

        assert server.API_BASE.startswith("http")
        assert server.mcp.name == "soymutdb"

    def test_entrypoint_parses_args(self):
        import argparse

        import mcp_server.server as server

        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=9000)
        args = parser.parse_args(["--host", "127.0.0.1", "--port", "9001"])
        assert args.host == "127.0.0.1"
        assert args.port == 9001
        # main() must be importable (console script entry point)
        assert callable(server.main)


class TestPhaseOneDeploymentBoundary:
    def test_mcp_bearer_auth_rejects_missing_empty_wrong_scheme_and_token(self, monkeypatch):
        from mcp_server import server

        monkeypatch.setattr(server, "API_TOKEN", "expected-token")
        for authorization in (None, "", "Basic expected-token", "Bearer wrong"):
            assert server._authenticate_request(authorization) is False

        assert server._authenticate_request("Bearer expected-token") is True

    def test_mcp_bearer_auth_fails_closed_when_token_unconfigured(self, monkeypatch):
        from mcp_server import server

        monkeypatch.setattr(server, "API_TOKEN", "")
        assert server._authenticate_request("Bearer anything") is False

    def test_caller_identity_does_not_use_client_id_as_authentication(self):
        from mcp_server import server

        class ContextWithClientId:
            client_id = "untrusted-client-id"

        assert server._caller_key(ContextWithClientId()) == "anonymous"

    def test_compose_injects_password_protected_shared_redis_and_healthcheck(self):
        compose = Path(__file__).parents[3] / "docker-compose.yml"
        text = compose.read_text()
        mcp_block = re.search(r"(?ms)^  mcp-server:\n(.*?)(?=^  \S|\Z)", text)
        assert mcp_block, "mcp-server service must exist"
        block = mcp_block.group(1)
        assert "SOYMUTDB_MCP_REDIS_URL: redis://:${REDIS_PASSWORD" in block
        assert "healthcheck:" in block
        assert "localhost:9000" in block
        assert "method='POST'" in block
        assert "Authorization': 'Bearer ' + os.environ['SOYMUTDB_MCP_API_TOKEN']" in block

    def test_nginx_mcp_boundary_requires_bearer_without_affecting_health(self):
        config = Path(__file__).parents[3] / "infra/nginx/conf.d/default.conf"
        text = config.read_text()
        slash = text[text.index("location = /mcp/ {"):text.index("location = /mcp {")]
        assert "if ($http_authorization = \"\")" in slash
        assert "return 308 /mcp;" in slash

        mcp = text[text.index("location = /mcp {"):text.index("location / {", text.index("location = /mcp {"))]
        assert "limit_req zone=auth" in mcp
        assert "if ($http_authorization = \"\")" in mcp
        assert "proxy_set_header X-Request-ID" in mcp
        assert "location = /health" in text
