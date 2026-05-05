import asyncio
import contextlib
import logging
import os
from typing import cast

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pyclaudius.backlog import BacklogItem
from pyclaudius.bot_data import BotData, SessionState
from pyclaudius.claude import call_claude
from pyclaudius.config import Settings
from pyclaudius.cron.models import ScheduledJob
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


_BUILTIN_TOOLS = ["Read", "Bash", "Edit", "Write"]


def _get_memory_section(*, settings: Settings, memory: list[str]) -> str | None:
    if settings.memory_enabled:
        return format_memory_section(memories=memory)
    return None


def _get_cron_count(*, settings: Settings, cron_jobs: list[ScheduledJob]) -> int | None:
    if settings.cron_enabled:
        return len(cron_jobs)
    return None


def _get_allowed_tools(*, settings: Settings, bot_data: BotData) -> list[str]:
    """Combine user-configured allowed tools with MCP tool names.

    When extra tools (settings or MCP) are specified, built-in tools are
    prepended so that ``--allowedTools`` does not accidentally restrict
    Claude from basic file operations.
    """
    extra = list(settings.allowed_tools) + bot_data["mcp_allowed_tools"]
    if extra:
        return _BUILTIN_TOOLS + extra
    return extra


async def _send_response(*, message: object, response: str) -> None:
    """Send response chunks to the user, with fallback for empty responses.

    A response containing ``[SILENT]`` is suppressed entirely — no reply
    is sent. Empty responses (the system-level "session broken" signal)
    still surface to the user as ``(empty response from Claude)``.
    """
    if has_silent_tag(text=response):
        logger.info("Response was [SILENT], suppressing reply")
        return
    chunks = split_response(text=response)
    if not chunks:
        await message.reply_text("(empty response from Claude)")
        return
    for chunk in chunks:
        await message.reply_text(chunk)


async def _run_claude(
    *, claude_lock: asyncio.Lock | None, **kwargs: object
) -> tuple[str, str | None]:
    """Invoke ``call_claude``, optionally serialised through the global lock.

    The lock is held for the full duration of the wrapped call (including
    the ``with_backlog`` retry path), so concurrent Telegram updates cannot
    overlap Claude CLI invocations.
    """
    if claude_lock is None:
        return await call_claude(**kwargs)
    async with claude_lock:
        return await call_claude(**kwargs)


def _persist_session_id(
    *, settings: Settings, session: SessionState, new_session_id: str | None
) -> None:
    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )


async def _claude_round_trip(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
    prompt_user_message: str,
    add_dirs: list[str] | None = None,
    is_scheduled: bool = False,
) -> tuple[str, str | None]:
    """Build a prompt, run Claude under the lock, persist the session id.

    ``user_message`` is the raw text used by ``with_backlog`` to save a
    backlog entry on recoverable failures; ``prompt_user_message`` is the
    (possibly decorated) text fed into ``build_prompt`` for Claude.
    """
    bot_data = cast(BotData, context.bot_data)
    settings = bot_data["settings"]
    session = bot_data["session"]

    prompt = build_prompt(
        user_message=prompt_user_message,
        memory_section=_get_memory_section(
            settings=settings, memory=bot_data["memory"]
        ),
        cron_count=_get_cron_count(settings=settings, cron_jobs=bot_data["cron_jobs"]),
        is_scheduled=is_scheduled,
        timezone=bot_data.get("user_timezone"),
    )

    call_kwargs: dict = dict(
        prompt=prompt,
        claude_path=settings.claude_path,
        session_id=session.get("session_id"),
        resume=True,
        allowed_tools=_get_allowed_tools(settings=settings, bot_data=bot_data),
        cwd=str(settings.claude_work_dir),
        timeout=settings.claude_timeout,
        bot_data=bot_data,
        user_message=user_message,
    )
    if add_dirs is not None:
        call_kwargs["add_dirs"] = add_dirs

    response, new_session_id = await _run_claude(
        claude_lock=bot_data.get("claude_lock"), **call_kwargs
    )
    _persist_session_id(
        settings=settings, session=session, new_session_id=new_session_id
    )
    return response, new_session_id


@authorized
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return

    scheduled_ids: set[int] = context.bot_data.get("_scheduled_update_ids", set())
    is_scheduled = update.update_id in scheduled_ids
    scheduled_ids.discard(update.update_id)

    text = update.message.text
    logger.info(f"Text from {update.effective_user.id}: {text[:50]}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    response, _ = await _claude_round_trip(
        context=context,
        user_message=text,
        prompt_user_message=text,
        is_scheduled=is_scheduled,
    )

    if is_scheduled and has_silent_tag(text=response):
        logger.info(
            f"Scheduled job {update.update_id} response was silent, not notifying user"
        )
        return

    await _send_response(message=update.message, response=response)


@authorized
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.photo:
        return

    logger.info(f"Photo from {update.effective_user.id}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_name = f"image_{update.message.message_id}.jpg"
    file_path = settings.uploads_dir / file_name
    await file.download_to_drive(custom_path=str(file_path))

    caption = update.message.caption or "Analyze this image."
    response, _ = await _claude_round_trip(
        context=context,
        user_message=caption,
        prompt_user_message=f"[Image: uploads/{file_name}]\n\n{caption}",
        add_dirs=[str(settings.uploads_dir)],
    )

    await _send_response(message=update.message, response=response)

    with contextlib.suppress(OSError):
        os.unlink(file_path)


@authorized
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming documents."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.document:
        return

    doc = update.message.document
    logger.info(f"Document from {update.effective_user.id}: {doc.file_name}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    file = await context.bot.get_file(doc.file_id)
    file_name = doc.file_name or "document"
    stored_name = f"{update.message.message_id}_{file_name}"
    file_path = settings.uploads_dir / stored_name
    await file.download_to_drive(custom_path=str(file_path))

    caption = update.message.caption or f"Analyze: {file_name}"
    response, _ = await _claude_round_trip(
        context=context,
        user_message=caption,
        prompt_user_message=f"[File: uploads/{stored_name}]\n\n{caption}",
        add_dirs=[str(settings.uploads_dir)],
    )

    await _send_response(message=update.message, response=response)

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

    result = remember_fact(fact=fact, bot_data=cast(BotData, context.bot_data))
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
        result = forget_memory(
            keyword=keyword, bot_data=cast(BotData, context.bot_data)
        )
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

    result = list_memories(bot_data=cast(BotData, context.bot_data))
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

    result = list_backlog(bot_data=cast(BotData, context.bot_data))
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

    result = clear_backlog(bot_data=cast(BotData, context.bot_data))
    await update.message.reply_text(result)


def _format_backlog_prompt(*, item: BacklogItem) -> str:
    return f"[Backlog — originally sent at {item['created_at']}]\n{item['prompt']}"


@authorized
async def handle_replaybacklog_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /replaybacklog command — replay all backlog items sequentially."""
    settings: Settings = context.bot_data["settings"]

    if not update.message:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    bot_data = cast(BotData, context.bot_data)
    backlog = bot_data["backlog"]
    if not backlog:
        await update.message.reply_text("Backlog is empty.")
        return

    count = len(backlog)
    await update.message.reply_text(f"Replaying {count} backlog item(s)...")

    while bot_data["backlog"]:
        item = remove_backlog_item(index=1, bot_data=bot_data)
        await update.message.chat.send_action(action=ChatAction.TYPING)

        response, _ = await _claude_round_trip(
            context=context,
            user_message=item["prompt"],
            prompt_user_message=_format_backlog_prompt(item=item),
        )

        await _send_response(message=update.message, response=response)

        # If the auth error hit again, the decorator already re-queued the
        # item — stop so we don't spin forever.
        if "Authentication error" in response and "backlog" in response:
            break


@authorized
async def handle_replayone_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /replayone <number> command — replay a single backlog item."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.backlog_enabled:
        await update.message.reply_text("Backlog is disabled.")
        return

    arg = update.message.text.removeprefix("/replayone").strip()
    if not arg or not arg.isdigit():
        await update.message.reply_text("Usage: /replayone <number>")
        return

    try:
        item = remove_backlog_item(
            index=int(arg), bot_data=cast(BotData, context.bot_data)
        )
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)

    response, _ = await _claude_round_trip(
        context=context,
        user_message=item["prompt"],
        prompt_user_message=_format_backlog_prompt(item=item),
    )

    await _send_response(message=update.message, response=response)


def _slash_command_kwargs(*, prompt: str, settings: Settings, session_id: str) -> dict:
    return dict(
        prompt=prompt,
        claude_path=settings.claude_path,
        session_id=session_id,
        resume=True,
        cwd=str(settings.claude_work_dir),
        timeout=settings.claude_timeout,
    )


@authorized
async def handle_clear_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /clear command — clear session and start fresh."""
    settings: Settings = context.bot_data["settings"]
    session: SessionState = context.bot_data["session"]

    if not update.message:
        return

    session_id = session.get("session_id")
    if session_id:
        await update.message.chat.send_action(action=ChatAction.TYPING)
        await _run_claude(
            claude_lock=context.bot_data.get("claude_lock"),
            **_slash_command_kwargs(
                prompt="/clear", settings=settings, session_id=session_id
            ),
        )

    session["session_id"] = None
    save_session(session_file=settings.session_file, session_id=None)
    await update.message.reply_text("Session cleared.")


@authorized
async def handle_compact_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /compact command — compact conversation context."""
    settings: Settings = context.bot_data["settings"]
    session: SessionState = context.bot_data["session"]

    if not update.message:
        return

    session_id = session.get("session_id")
    if not session_id:
        await update.message.reply_text("No active session to compact.")
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)

    response, new_session_id = await _run_claude(
        claude_lock=context.bot_data.get("claude_lock"),
        **_slash_command_kwargs(
            prompt="/compact", settings=settings, session_id=session_id
        ),
    )
    _persist_session_id(
        settings=settings, session=session, new_session_id=new_session_id
    )
    await _send_response(message=update.message, response=response)


@authorized
async def handle_context_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /context command — show context window usage."""
    settings: Settings = context.bot_data["settings"]
    session: SessionState = context.bot_data["session"]

    if not update.message:
        return

    session_id = session.get("session_id")
    if not session_id:
        await update.message.reply_text("No active session.")
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)

    response, new_session_id = await _run_claude(
        claude_lock=context.bot_data.get("claude_lock"),
        **_slash_command_kwargs(
            prompt="/context", settings=settings, session_id=session_id
        ),
    )
    _persist_session_id(
        settings=settings, session=session, new_session_id=new_session_id
    )
    await _send_response(message=update.message, response=response)


@authorized
async def handle_help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /help command — show available commands."""
    if not update.message:
        return

    help_text = (
        "Available commands:\n\n"
        "/help — show available commands\n"
        "/clear — clear session and start fresh\n"
        "/compact — compact conversation context\n"
        "/context — show context window usage\n"
        "/timezone <city> — set timezone (fuzzy match)\n"
        "/remember <fact> — store a memory fact\n"
        "/listmemory — list all stored memories\n"
        "/forget <keyword or number> — remove memories matching keyword or by index\n"
        "/addcron <min> <hour> <day> <month> <weekday> <prompt> — add a recurring cron job\n"
        "/schedule <datetime> | <prompt> — schedule a one-time task\n"
        "/listcron — list all scheduled jobs\n"
        "/removecron <number> — remove a scheduled job by number\n"
        "/testcron <number> — immediately test a scheduled job\n"
        "/listbacklog — show pending backlog items\n"
        "/clearbacklog — clear all backlog items\n"
        "/replaybacklog — replay all backlog items\n"
        "/replayone <number> — replay a single backlog item\n\n"
        "Text, photo, and document messages are forwarded to Claude."
    )
    await update.message.reply_text(help_text)
