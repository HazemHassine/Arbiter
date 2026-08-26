import asyncio

import pytest

from arbiter.integrations.a2a.server import AGENT_CARD


def test_a2a_capability_card():
    assert AGENT_CARD["name"] == "Arbiter"
    assert AGENT_CARD["skills"][0]["id"] == "prepare_project"


def test_optional_mcp_server_registers_high_level_tools():
    pytest.importorskip("mcp")
    from arbiter.integrations.mcp.server import create_server

    names = {tool.name for tool in asyncio.run(create_server().list_tools())}
    assert "arbiter_prepare_project" in names
    assert "ports_detect_conflicts" in names
