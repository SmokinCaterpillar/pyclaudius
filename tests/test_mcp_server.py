from unittest.mock import MagicMock

import pytest

from pyclaudius.mcp_tools.config import MCP_SERVER_NAME
from pyclaudius.mcp_tools.server import create_mcp_server, mcp_tool_names


def _bot_data(**flags) -> dict:
    attrs = {
        "cron_enabled": False,
        "memory_enabled": False,
        "email_enabled": False,
        "backlog_enabled": False,
        "max_memories": 100,
    }
    attrs.update(flags)
    settings = MagicMock(**attrs)
    return {
        "settings": settings,
        "memory": [],
        "cron_jobs": [],
        "backlog": [],
        "scheduler": MagicMock(),
        "application": MagicMock(),
    }


@pytest.mark.parametrize(
    "flags",
    [
        {},
        {"cron_enabled": True},
        {"memory_enabled": True},
        {"email_enabled": True},
        {"backlog_enabled": True},
        {
            "cron_enabled": True,
            "memory_enabled": True,
            "email_enabled": True,
            "backlog_enabled": True,
        },
    ],
)
async def test_tool_names_match_the_running_server(flags):
    """The generated permission map must list exactly the tools that exist.

    ``mcp_tool_names`` is a static table, so this pins it to the server the
    factory actually builds — otherwise a new tool would be exposed with no
    matching "allow" entry, or a stale name would linger in the config.
    """
    bot_data = _bot_data(**flags)
    server = create_mcp_server(bot_data=bot_data)
    registered = {f"{MCP_SERVER_NAME}_{name}" for name in await server.get_tools()}
    assert set(mcp_tool_names(settings=bot_data["settings"])) == registered


def test_tool_names_use_opencode_namespacing():
    """MCP tools are addressed as ``<server>_<tool>`` by opencode, verified live."""
    bot_data = _bot_data(cron_enabled=True)
    names = mcp_tool_names(settings=bot_data["settings"])
    assert "pyclaudius_list_cron_jobs" in names
    assert all(name.startswith("pyclaudius_") for name in names)


def test_tool_names_empty_when_all_features_disabled():
    assert mcp_tool_names(settings=_bot_data()["settings"]) == []
