import contextlib
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pyclaudius.claude import call_claude
from pyclaudius.config import Settings
from pyclaudius.memory import format_memory_section
from pyclaudius.operations import (
    clear_backlog,
    forget_memory,
    list_backlog,
    list_memories,
    remember_fact,
    remove_backlog_item,
)
from pyclaudius.prompt import build_prompt
from pyclaudius.response import has_silent_tag, split_response
from pyclaudius.session import save_session
from pyclaudius.timezone import find_timezones, save_timezone
from pyclaudius.tooling import authorized

logger = logging.getLogger(__name__)


def _get_memory_section(*, settings: Settings, memory: list[str]) -> str | None:
    """Build the memory section for the prompt if memory is enabled."""
    if settings.memory_enabled:
        return format_memory_section(memories=memory)
    return None


def _get_cron_count(*, settings: Settings, cron_jobs: list[dict]) -> int | None:
    """Return cron job count if cron is enabled, else None."""
    if settings.cron_enabled:
        return len(cron_jobs)
    return None


def _get_allowed_tools(*, settings: Settings, bot_data: dict) -> list[str]:
    """Combine user-configured allowed tools with MCP tool names."""
    mcp_tools: list[str] = bot_data.get("mcp_allowed_tools", [])
    return list(settings.allowed_tools) + mcp_tools



@authorized
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.message or not update.message.text:
        return

    scheduled_ids: set[int] = context.bot_data.get("_scheduled_update_ids", set())
    is_scheduled = update.update_id in scheduled_ids
    scheduled_ids.discard(update.update_id)

    logger.info(f"Text from {update.effective_user.id}: {update.message.text[:50]}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    memory: list[str] = context.bot_data.get("memory", [])
    cron_jobs: list[dict] = context.bot_data.get("cron_jobs", [])
    user_tz: str | None = context.bot_data.get("user_timezone")
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=update.message.text,
        memory_section=memory_section,
        cron_count=cron_count,
        is_scheduled=is_scheduled,
        timezone=user_tz,
    )

    claude_lock = context.bot_data.get("claude_lock")
    if claude_lock:
        async with claude_lock:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
                cwd=str(settings.claude_work_dir),
                bot_data=context.bot_data,
                user_message=update.message.text,
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
            cwd=str(settings.claude_work_dir),
            bot_data=context.bot_data,
            user_message=update.message.text,
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    if is_scheduled and has_silent_tag(text=response):
        logger.info(
            f"Scheduled job {update.update_id} response was silent, not notifying user"
        )
        return

    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)


@authorized
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.message or not update.message.photo:
        return

    logger.info(f"Photo from {update.effective_user.id}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_path = settings.uploads_dir / f"image_{update.message.message_id}.jpg"
    await file.download_to_drive(custom_path=str(file_path))

    caption = update.message.caption or "Analyze this image."
    memory: list[str] = context.bot_data.get("memory", [])
    cron_jobs: list[dict] = context.bot_data.get("cron_jobs", [])
    user_tz: str | None = context.bot_data.get("user_timezone")
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=f"[Image: {file_path}]\n\n{caption}",
        memory_section=memory_section,
        cron_count=cron_count,
        timezone=user_tz,
    )

    claude_lock = context.bot_data.get("claude_lock")
    if claude_lock:
        async with claude_lock:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                add_dirs=[str(settings.uploads_dir)],
                allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
                cwd=str(settings.claude_work_dir),
                bot_data=context.bot_data,
                user_message=caption,
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            add_dirs=[str(settings.uploads_dir)],
            allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
            cwd=str(settings.claude_work_dir),
            bot_data=context.bot_data,
            user_message=caption,
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)

    with contextlib.suppress(OSError):
        os.unlink(file_path)


@authorized
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming documents."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.message or not update.message.document:
        return

    doc = update.message.document
    logger.info(f"Document from {update.effective_user.id}: {doc.file_name}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    file = await context.bot.get_file(doc.file_id)
    file_name = doc.file_name or "document"
    file_path = settings.uploads_dir / f"{update.message.message_id}_{file_name}"
    await file.download_to_drive(custom_path=str(file_path))

    caption = update.message.caption or f"Analyze: {file_name}"
    memory: list[str] = context.bot_data.get("memory", [])
    cron_jobs: list[dict] = context.bot_data.get("cron_jobs", [])
    user_tz: str | None = context.bot_data.get("user_timezone")
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=f"[File: {file_path}]\n\n{caption}",
        memory_section=memory_section,
        cron_count=cron_count,
        timezone=user_tz,
    )

    claude_lock = context.bot_data.get("claude_lock")
    if claude_lock:
        async with claude_lock:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                add_dirs=[str(settings.uploads_dir)],
                allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
                cwd=str(settings.claude_work_dir),
                bot_data=context.bot_data,
                user_message=caption,
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            add_dirs=[str(settings.uploads_dir)],
            allowed_tools=_get_allowed_tools(settings=settings, bot_data=context.bot_data),
            cwd=str(settings.claude_work_dir),
            bot_data=context.bot_data,
            user_message=caption,
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)

    with contextlib.suppress(OSError):
        os.unlink(file_path)


@authorized
async def handle_remember_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /remember <fact> command — store a memory fact."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.memory_enabled:
        await update.message.reply_text("Memory is disabled.")
        return

    fact = update.message.text.removeprefix("/remember").strip()
    if not fact:
        await update.message.reply_text("Usage: /remember <fact>")
        return

    result = remember_fact(fact=fact, bot_data=context.bot_data)
    await update.message.reply_text(result)


@authorized
async def handle_forget_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /forget <keyword> command — remove matching memories."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.memory_enabled:
        await update.message.reply_text("Memory is disabled.")
        return

    keyword = update.message.text.removeprefix("/forget").strip()
    if not keyword:
        await update.message.reply_text("Usage: /forget <keyword or number>")
        return

    try:
        result = forget_memory(keyword=keyword, bot_data=context.bot_data)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(result)


@authorized
async def handle_listmemory_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /listmemory command — list stored memory facts."""
    settings: Settings = context.bot_data["settings"]

    if not update.message:
        return

    if not settings.memory_enabled:
        await update.message.reply_text("Memory is disabled.")
        return

    result = list_memories(bot_data=context.bot_data)
    await update.message.reply_text(result)


@authorized
async def handle_timezone_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /timezone <city> command — set timezone with fuzzy matching."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    query = update.message.text.removeprefix("/timezone").strip()
    current_tz: str | None = context.bot_data.get("user_timezone")

    if not query:
        tz_display = current_tz or "UTC (default)"
        await update.message.reply_text(
            f"Current timezone: {tz_display}\n\n"
            "Usage: /timezone <city>\n"
            "Example: /timezone Berlin"
        )
        return

    matches = find_timezones(query=query)

    if not matches:
        await update.message.reply_text(
            f'No timezone found for "{query}". Try a city name like Berlin, Tokyo, or New York.'
        )
        return

    # Auto-select if single match or first match's city component equals query
    normalized_query = query.lower().replace(" ", "_")
    first_city = matches[0].rsplit("/", maxsplit=1)[-1].lower()
    if len(matches) == 1 or first_city == normalized_query:
        selected = matches[0]
        context.bot_data["user_timezone"] = selected
        save_timezone(timezone_file=settings.timezone_file, timezone=selected)
        logger.info(f"Timezone set to {selected}")
        await update.message.reply_text(f"Timezone set to {selected}")
        return

    # Multiple ambiguous matches — show top 10
    shown = matches[:10]
    lines = "\n".join(f"  {tz}" for tz in shown)
    extra = f"\n  ... and {len(matches) - 10} more" if len(matches) > 10 else ""
    await update.message.reply_text(
        f'Multiple timezones match "{query}":\n{lines}{extra}\n\n'
        "Please be more specific."
    )


@authorized
async def handle_listbacklog_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /listbacklog command — show pending backlog items."""
    settings: Settings = context.bot_data["settings"]

    if not update.message:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    result = list_backlog(bot_data=context.bot_data)
    await update.message.reply_text(result)


@authorized
async def handle_clearbacklog_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /clearbacklog command — clear all backlog items."""
    settings: Settings = context.bot_data["settings"]

    if not update.message:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    result = clear_backlog(bot_data=context.bot_data)
    await update.message.reply_text(result)


@authorized
async def handle_replaybacklog_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /replaybacklog command — replay all backlog items sequentially."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.message:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    backlog: list[dict] = context.bot_data.get("backlog", [])
    if not backlog:
        await update.message.reply_text("Backlog is empty.")
        return

    count = len(backlog)
    await update.message.reply_text(f"Replaying {count} backlog item(s)...")

    while context.bot_data.get("backlog"):
        item = remove_backlog_item(index=1, bot_data=context.bot_data)
        await update.message.chat.send_action(action=ChatAction.TYPING)

        memory: list[str] = context.bot_data.get("memory", [])
        cron_jobs: list[dict] = context.bot_data.get("cron_jobs", [])
        user_tz: str | None = context.bot_data.get("user_timezone")
        memory_section = _get_memory_section(settings=settings, memory=memory)
        cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
        backlog_msg = (
            f"[Backlog — originally sent at {item['created_at']}]\n"
            f"{item['prompt']}"
        )
        prompt = build_prompt(
            user_message=backlog_msg,
            memory_section=memory_section,
            cron_count=cron_count,
            timezone=user_tz,
        )

        claude_lock = context.bot_data.get("claude_lock")
        if claude_lock:
            async with claude_lock:
                response, new_session_id = await call_claude(
                    prompt=prompt,
                    claude_path=settings.claude_path,
                    session_id=session.get("session_id"),
                    resume=True,
                    allowed_tools=_get_allowed_tools(
                        settings=settings, bot_data=context.bot_data
                    ),
                    cwd=str(settings.claude_work_dir),
                    bot_data=context.bot_data,
                    user_message=item["prompt"],
                )
        else:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                allowed_tools=_get_allowed_tools(
                    settings=settings, bot_data=context.bot_data
                ),
                cwd=str(settings.claude_work_dir),
                bot_data=context.bot_data,
                user_message=item["prompt"],
            )

        if new_session_id:
            session["session_id"] = new_session_id
        save_session(
            session_file=settings.session_file,
            session_id=session.get("session_id"),
        )

        for chunk in split_response(text=response):
            await update.message.reply_text(chunk)

        # If auth error hit again, decorator already re-added to backlog — stop
        if "Authentication error" in response and "backlog" in response:
            break


@authorized
async def handle_replayone_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /replayone <number> command — replay a single backlog item."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.message or not update.message.text:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    arg = update.message.text.removeprefix("/replayone").strip()
    if not arg or not arg.isdigit():
        await update.message.reply_text("Usage: /replayone <number>")
        return

    index = int(arg)
    try:
        item = remove_backlog_item(index=index, bot_data=context.bot_data)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)

    memory: list[str] = context.bot_data.get("memory", [])
    cron_jobs: list[dict] = context.bot_data.get("cron_jobs", [])
    user_tz: str | None = context.bot_data.get("user_timezone")
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    backlog_msg = (
        f"[Backlog — originally sent at {item['created_at']}]\n"
        f"{item['prompt']}"
    )
    prompt = build_prompt(
        user_message=backlog_msg,
        memory_section=memory_section,
        cron_count=cron_count,
        timezone=user_tz,
    )

    claude_lock = context.bot_data.get("claude_lock")
    if claude_lock:
        async with claude_lock:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                allowed_tools=_get_allowed_tools(
                    settings=settings, bot_data=context.bot_data
                ),
                cwd=str(settings.claude_work_dir),
                bot_data=context.bot_data,
                user_message=item["prompt"],
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            allowed_tools=_get_allowed_tools(
                settings=settings, bot_data=context.bot_data
            ),
            cwd=str(settings.claude_work_dir),
            bot_data=context.bot_data,
            user_message=item["prompt"],
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)


@authorized
async def handle_help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /help command — show available commands."""
    if not update.message:
        return

    help_text = (
        "Available commands:\n\n"
        "/help \u2014 show available commands\n"
        "/timezone <city> \u2014 set timezone (fuzzy match)\n"
        "/remember <fact> \u2014 store a memory fact\n"
        "/listmemory \u2014 list all stored memories\n"
        "/forget <keyword or number> \u2014 remove memories matching keyword or by index\n"
        "/addcron <min> <hour> <day> <month> <weekday> <prompt> \u2014 add a recurring cron job\n"
        "/schedule <datetime> | <prompt> \u2014 schedule a one-time task\n"
        "/listcron \u2014 list all scheduled jobs\n"
        "/removecron <number> \u2014 remove a scheduled job by number\n"
        "/testcron <number> \u2014 immediately test a scheduled job\n"
        "/listbacklog \u2014 show pending backlog items\n"
        "/clearbacklog \u2014 clear all backlog items\n"
        "/replaybacklog \u2014 replay all backlog items\n"
        "/replayone <number> \u2014 replay a single backlog item\n\n"
        "Text, photo, and document messages are forwarded to Claude."
    )
    await update.message.reply_text(help_text)
