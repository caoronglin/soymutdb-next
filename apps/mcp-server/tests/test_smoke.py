"""MCP server smoke tests (B1): import + tool inventory present."""

from __future__ import annotations

import asyncio


def _tool_names() -> list[str]:
    from mcp_server.server import mcp

    return [t.name for t in asyncio.run(mcp.list_tools())]


class TestToolRegistry:
    def test_all_manifest_tools_registered(self):
        from mcp_server.manifest import TOOLS

        names = set(_tool_names())
        expected = {t["name"] for t in TOOLS}
        assert expected == names
        assert len(names) == 7

    def test_tool_read_write_split(self):
        from mcp_server.manifest import TOOLS

        read = {t["name"] for t in TOOLS if t["type"] == "read"}
        write = {t["name"] for t in TOOLS if t["type"] == "write"}
        assert read == {"gene_by_id", "variant_by_region", "news_list", "stats_summary", "seqfetch"}
        assert write == {"blast_submit", "analyses_query"}


class TestManifest:
    def test_manifest_shape(self):
        from mcp_server.manifest import AUTH, MANIFEST, SERVER_NAME, VERSION, TOOLS

        assert MANIFEST["server"] == SERVER_NAME == "soymutdb"
        assert MANIFEST["version"] == VERSION
        assert MANIFEST["tools"] is TOOLS
        assert "rate_limit" in AUTH
        assert "60 req/min" in AUTH["rate_limit"]


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
