"""MCP server factory — closure-based, no globals."""

import logging

from fastmcp import FastMCP

from pyclaudius import operations

logger = logging.getLogger(__name__)


def create_mcp_server(*, bot_data: dict) -> FastMCP:
    """Create a FastMCP server with tools bound to bot_data via closure."""
    mcp = FastMCP("pyclaudius")
    settings = bot_data["settings"]

    if settings.cron_enabled:

        @mcp.tool()
        async def list_cron_jobs() -> str:
            """List all scheduled cron jobs with their expressions, timezones, and prompts."""
            return operations.list_cron_jobs(bot_data=bot_data)

        @mcp.tool()
        async def add_cron_job(expression: str, prompt: str) -> str:
            """Add a recurring cron job. Use a standard 5-field cron expression."""
            try:
                return operations.add_cron_job(
                    expression=expression, prompt_text=prompt, bot_data=bot_data
                )
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def schedule_once(datetime_str: str, prompt: str) -> str:
            """Schedule a one-time task at a specific datetime (YYYY-MM-DD HH:MM)."""
            try:
                return operations.schedule_once(
                    datetime_str=datetime_str, prompt_text=prompt, bot_data=bot_data
                )
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def remove_cron_job(index: int) -> str:
            """Remove a scheduled job by its 1-based index number."""
            try:
                return operations.remove_cron_job(index=index, bot_data=bot_data)
            except ValueError as e:
                return str(e)

    if settings.memory_enabled:

        @mcp.tool()
        async def remember_fact(fact: str) -> str:
            """Remember an important fact about the user."""
            return operations.remember_fact(fact=fact, bot_data=bot_data)

        @mcp.tool()
        async def forget_memory(keyword: str) -> str:
            """Forget memories matching a keyword or by index number."""
            try:
                return operations.forget_memory(keyword=keyword, bot_data=bot_data)
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def list_memories() -> str:
            """List all stored memory facts about the user."""
            return operations.list_memories(bot_data=bot_data)

    return mcp


def get_allowed_tools_wildcard() -> str:
    """Return an ``--allowedTools`` wildcard pattern for all pyclaudius MCP tools."""
    from pyclaudius.mcp_tools.config import MCP_SERVER_NAME

    return f"mcp__{MCP_SERVER_NAME}__*"
