import contextlib
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pyclaudius.claude import call_claude
from pyclaudius.config import Settings
from pyclaudius.cron.handlers import process_cron_response
from pyclaudius.cron.tags import has_silent_tag
from pyclaudius.memory import (
    add_memories,
    extract_forget_tags,
    extract_remember_tags,
    format_memory_section,
    remove_memories,
    save_memory,
    strip_remember_tags,
)
from pyclaudius.prompt import build_prompt
from pyclaudius.response import split_response
from pyclaudius.session import save_session
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


def _process_memory_response(
    *, response: str, settings: Settings, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Extract REMEMBER/FORGET tags from response, update memory, return cleaned response."""
    if not settings.memory_enabled:
        return response

    memory: list[str] = context.bot_data.get("memory", [])
    changed = False

    forget_keywords = extract_forget_tags(text=response)
    if forget_keywords:
        memory = remove_memories(existing=memory, keywords=forget_keywords)
        changed = True
        logger.info(f"Forgot memories matching: {forget_keywords}")

    overflow_warning = ""
    new_facts = extract_remember_tags(text=response)
    if new_facts:
        memory_before = list(memory)
        unique_new = [
            f for f in new_facts if f.lower() not in {m.lower() for m in memory}
        ]
        memory = add_memories(
            existing=memory,
            new=new_facts,
            max_memories=settings.max_memories,
        )
        changed = True
        logger.info(f"Stored {len(new_facts)} new memory fact(s), total: {len(memory)}")
        overflow_count = len(memory_before) + len(unique_new) - settings.max_memories
        if overflow_count > 0:
            dropped = memory_before[:overflow_count]
            dropped_list = ", ".join(f'"{d}"' for d in dropped)
            overflow_warning = (
                f"\n\n⚠ Memory full ({settings.max_memories}). "
                f"Oldest fact(s) forgotten: {dropped_list}"
            )

    if changed:
        context.bot_data["memory"] = memory
        save_memory(memory_file=settings.memory_file, memories=memory)

    return strip_remember_tags(text=response) + overflow_warning


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
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=update.message.text,
        memory_section=memory_section,
        cron_count=cron_count,
        is_scheduled=is_scheduled,
    )

    claude_lock = context.bot_data.get("claude_lock")
    if claude_lock:
        async with claude_lock:
            response, new_session_id = await call_claude(
                prompt=prompt,
                claude_path=settings.claude_path,
                session_id=session.get("session_id"),
                resume=True,
                allowed_tools=settings.allowed_tools,
                cwd=str(settings.claude_work_dir),
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            allowed_tools=settings.allowed_tools,
            cwd=str(settings.claude_work_dir),
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(
        response=response, settings=settings, context=context
    )
    response = process_cron_response(
        response=response, settings=settings, context=context
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
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=f"[Image: {file_path}]\n\n{caption}",
        memory_section=memory_section,
        cron_count=cron_count,
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
                allowed_tools=settings.allowed_tools,
                cwd=str(settings.claude_work_dir),
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            add_dirs=[str(settings.uploads_dir)],
            allowed_tools=settings.allowed_tools,
            cwd=str(settings.claude_work_dir),
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(
        response=response, settings=settings, context=context
    )
    response = process_cron_response(
        response=response, settings=settings, context=context
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
    memory_section = _get_memory_section(settings=settings, memory=memory)
    cron_count = _get_cron_count(settings=settings, cron_jobs=cron_jobs)
    prompt = build_prompt(
        user_message=f"[File: {file_path}]\n\n{caption}",
        memory_section=memory_section,
        cron_count=cron_count,
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
                allowed_tools=settings.allowed_tools,
                cwd=str(settings.claude_work_dir),
            )
    else:
        response, new_session_id = await call_claude(
            prompt=prompt,
            claude_path=settings.claude_path,
            session_id=session.get("session_id"),
            resume=True,
            add_dirs=[str(settings.uploads_dir)],
            allowed_tools=settings.allowed_tools,
            cwd=str(settings.claude_work_dir),
        )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(
        response=response, settings=settings, context=context
    )
    response = process_cron_response(
        response=response, settings=settings, context=context
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

    memory_before: list[str] = context.bot_data.get("memory", [])
    is_new = fact.lower() not in {f.lower() for f in memory_before}
    memory = add_memories(
        existing=memory_before,
        new=[fact],
        max_memories=settings.max_memories,
    )
    context.bot_data["memory"] = memory
    save_memory(memory_file=settings.memory_file, memories=memory)
    logger.info(f"Manually stored memory: {fact}")

    reply = f'Remembered: "{fact}"'
    if is_new and len(memory_before) >= settings.max_memories:
        dropped = memory_before[0]
        reply += f'\n\nWarning: memory full ({settings.max_memories}). Oldest fact forgotten: "{dropped}"'
    await update.message.reply_text(reply)


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

    memory: list[str] = context.bot_data.get("memory", [])

    # Index-based removal: /forget 3
    if keyword.isdigit():
        index = int(keyword)
        if index < 1 or index > len(memory):
            await update.message.reply_text(
                f"Invalid index {index}. Use /listmemory to see valid numbers (1\u2013{len(memory)})."
            )
            return
        removed_fact = memory.pop(index - 1)
        context.bot_data["memory"] = memory
        save_memory(memory_file=settings.memory_file, memories=memory)
        await update.message.reply_text(f'Removed memory {index}: "{removed_fact}"')
        return

    # Keyword-based removal
    updated = remove_memories(existing=memory, keywords=[keyword])
    removed_count = len(memory) - len(updated)

    if removed_count == 0:
        await update.message.reply_text(f'No memories matching "{keyword}".')
        return

    context.bot_data["memory"] = updated
    save_memory(memory_file=settings.memory_file, memories=updated)
    await update.message.reply_text(
        f'Removed {removed_count} memory/memories matching "{keyword}".'
    )


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

    memory: list[str] = context.bot_data.get("memory", [])
    if not memory:
        await update.message.reply_text("No memories stored.")
        return

    lines = "\n".join(f"{i + 1}. {fact}" for i, fact in enumerate(memory))
    await update.message.reply_text(f"Stored memories ({len(memory)}):\n\n{lines}")


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
        "/remember <fact> \u2014 store a memory fact\n"
        "/listmemory \u2014 list all stored memories\n"
        "/forget <keyword or number> \u2014 remove memories matching keyword or by index\n"
        "/addcron <min> <hour> <day> <month> <weekday> <prompt> \u2014 add a recurring cron job\n"
        "/schedule <datetime> | <prompt> \u2014 schedule a one-time task\n"
        "/listcron \u2014 list all scheduled jobs\n"
        "/removecron <number> \u2014 remove a scheduled job by number\n\n"
        "Text, photo, and document messages are forwarded to Claude."
    )
    await update.message.reply_text(help_text)
