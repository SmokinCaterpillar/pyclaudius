"""MCP server factory — closure-based, no globals."""

import logging

from fastmcp import FastMCP

from pyclaudius import operations
from pyclaudius.backlog import BacklogItem
from pyclaudius.bot_data import BotData
from pyclaudius.config import Settings

logger = logging.getLogger(__name__)


def create_mcp_server(*, bot_data: BotData) -> FastMCP:
    """Create a FastMCP server with tools bound to bot_data via closure."""
    mcp = FastMCP("pyclaudius")
    settings = bot_data["settings"]

    if settings.cron_enabled:

        @mcp.tool()
        async def list_cron_jobs() -> str:
            """List all scheduled cron jobs with their expressions, timezones, and prompts."""
            return operations.list_cron_jobs(bot_data=bot_data)

        @mcp.tool()
        async def add_cron_job(*, expression: str, prompt: str) -> str:
            """Add a recurring cron job. Use a standard 5-field cron expression."""
            try:
                return operations.add_cron_job(
                    expression=expression, prompt_text=prompt, bot_data=bot_data
                )
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def schedule_once(*, datetime_str: str, prompt: str) -> str:
            """Schedule a one-time task at a specific datetime (YYYY-MM-DD HH:MM)."""
            try:
                return operations.schedule_once(
                    datetime_str=datetime_str, prompt_text=prompt, bot_data=bot_data
                )
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def remove_cron_job(*, index: int) -> str:
            """Remove a scheduled job by its 1-based index number."""
            try:
                return operations.remove_cron_job(index=index, bot_data=bot_data)
            except ValueError as e:
                return str(e)

    if settings.memory_enabled:

        @mcp.tool()
        async def remember_fact(*, fact: str) -> str:
            """Remember an important fact about the user."""
            return operations.remember_fact(fact=fact, bot_data=bot_data)

        @mcp.tool()
        async def forget_memory(*, keyword: str) -> str:
            """Forget memories matching a keyword or by index number."""
            try:
                return operations.forget_memory(keyword=keyword, bot_data=bot_data)
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def list_memories() -> str:
            """List all stored memory facts about the user."""
            return operations.list_memories(bot_data=bot_data)

    if settings.email_enabled:

        @mcp.tool()
        async def download_new_mail() -> str:
            """Download unseen emails from the configured IMAP account and save as markdown files."""
            try:
                return operations.download_new_mail_op(bot_data=bot_data)
            except Exception as e:
                return f"Failed to download emails: {e}"

        @mcp.tool()
        async def delete_read_mail() -> str:
            """Delete all read (SEEN) emails from the configured IMAP account."""
            try:
                return operations.delete_read_mail_op(bot_data=bot_data)
            except Exception as e:
                return f"Failed to delete emails: {e}"

    if settings.backlog_enabled:

        @mcp.tool()
        async def list_backlog() -> str:
            """List all pending backlog items (messages saved after auth errors)."""
            return operations.list_backlog(bot_data=bot_data)

        @mcp.tool()
        async def clear_backlog() -> str:
            """Clear all pending backlog items."""
            return operations.clear_backlog(bot_data=bot_data)

        @mcp.tool()
        async def replay_one(*, index: int) -> str:
            """Pop a single backlog item by 1-based index and return its prompt text."""
            try:
                item = operations.remove_backlog_item(index=index, bot_data=bot_data)
                return item["prompt"]
            except ValueError as e:
                return str(e)

        @mcp.tool()
        async def replay_backlog() -> str:
            """Pop all backlog items and return their prompts as text."""
            items: list[BacklogItem] = bot_data["backlog"]
            if not items:
                return "Backlog is empty."
            prompts: list[str] = []
            while bot_data.get("backlog"):
                item = operations.remove_backlog_item(index=1, bot_data=bot_data)
                prompts.append(item["prompt"])
            return "\n\n---\n\n".join(prompts)

    return mcp


# Tools registered by ``create_mcp_server``, grouped by the setting that gates
# them. ``test_mcp_server`` asserts this stays in step with the real server, so
# the permission map can never silently drift from what is actually exposed.
_TOOLS_BY_FLAG: dict[str, tuple[str, ...]] = {
    "cron_enabled": (
        "list_cron_jobs",
        "add_cron_job",
        "schedule_once",
        "remove_cron_job",
    ),
    "memory_enabled": ("remember_fact", "forget_memory", "list_memories"),
    "email_enabled": ("download_new_mail", "delete_read_mail"),
    "backlog_enabled": (
        "list_backlog",
        "clear_backlog",
        "replay_one",
        "replay_backlog",
    ),
}


def mcp_tool_names(*, settings: Settings) -> list[str]:
    """Return the enabled MCP tool names as opencode addresses them.

    opencode namespaces MCP tools as ``<server>_<tool>`` (verified against a
    live run: ``pyclaudius_list_cron_jobs``), unlike the Claude CLI's
    ``mcp__<server>__<tool>``. Names are enumerated rather than wildcarded so
    the generated permission map lists exactly what exists.
    """
    from pyclaudius.mcp_tools.config import MCP_SERVER_NAME

    names: list[str] = []
    for flag, tools in _TOOLS_BY_FLAG.items():
        if getattr(settings, flag):
            names.extend(f"{MCP_SERVER_NAME}_{tool}" for tool in tools)
    return names
