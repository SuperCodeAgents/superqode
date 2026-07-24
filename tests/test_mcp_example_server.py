"""Tests for the runnable MCP HarnessSpec example."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastmcp import Client

from superqode.harness import harness_mcp_server_configs, load_harness_spec
from superqode.mcp.config import MCPStdioConfig


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "examples" / "mcp" / "local_docs_server.py"
HARNESS_PATH = ROOT / "examples" / "harnesses" / "mcp-docs.yaml"


def _load_example_server():
    spec = spec_from_file_location("superqode_local_docs_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


@pytest.mark.asyncio
async def test_local_docs_server_lists_and_calls_search_tool():
    async with Client(_load_example_server()) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["search_docs"]

        result = await client.call_tool("search_docs", {"query": "HarnessSpec", "limit": 1})

    assert result.data
    assert result.data[0]["path"].startswith("docs/")
    assert "HarnessSpec" in result.data[0]["excerpt"]


def test_mcp_docs_harness_points_to_runnable_stdio_server():
    harness = load_harness_spec(HARNESS_PATH)
    servers = harness_mcp_server_configs(harness)

    config = servers["docs"].config
    assert isinstance(config, MCPStdioConfig)
    assert config.command == "uv"
    assert config.args == ["run", "python", "examples/mcp/local_docs_server.py"]
