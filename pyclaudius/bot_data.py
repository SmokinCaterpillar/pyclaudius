"""Typed shape of ``context.bot_data`` for editor + mypy support."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fastmcp import FastMCP
    from telegram.ext import Application

    from pyclaudius.backlog import BacklogItem
    from pyclaudius.config import Settings
    from pyclaudius.cron.models import ScheduledJob


class SessionState(TypedDict):
    session_id: str | None
    last_activity: str


class BotData(TypedDict):
    settings: Settings
    application: Application
    session: SessionState
    memory: list[str]
    backlog: list[BacklogItem]
    cron_jobs: list[ScheduledJob]
    user_timezone: str | None
    claude_lock: asyncio.Lock
    mcp_server: FastMCP
    mcp_port: int
    mcp_allowed_tools: list[str]
    _scheduled_update_ids: set[int]
    scheduler: NotRequired[AsyncIOScheduler]
    mcp_task: NotRequired[asyncio.Task]
