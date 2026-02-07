import contextlib
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pyclaudius.claude import call_claude
from pyclaudius.config import Settings
from pyclaudius.memory import (
    add_memories,
    extract_remember_tags,
    format_memory_section,
    save_memory,
    strip_remember_tags,
)
from pyclaudius.prompt import build_prompt
from pyclaudius.response import split_response
from pyclaudius.session import save_session

logger = logging.getLogger(__name__)


def check_authorized(user_id: int, *, allowed_user_id: str) -> bool:
    """Check if a Telegram user ID is authorized."""
    return str(user_id) == allowed_user_id


def _get_memory_section(*, settings: Settings, memory: list[str]) -> str | None:
    """Build the memory section for the prompt if memory is enabled."""
    if settings.memory_enabled:
        return format_memory_section(memories=memory)
    return None


def _process_memory_response(
    *, response: str, settings: Settings, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Extract REMEMBER tags from response, update memory, return cleaned response."""
    if not settings.memory_enabled:
        return response

    new_facts = extract_remember_tags(text=response)
    if new_facts:
        memory: list[str] = context.bot_data.get("memory", [])
        updated = add_memories(
            existing=memory,
            new=new_facts,
            max_memories=settings.max_memories,
        )
        context.bot_data["memory"] = updated
        save_memory(memory_file=settings.memory_file, memories=updated)
        logger.info(f"Stored {len(new_facts)} new memory fact(s), total: {len(updated)}")

    return strip_remember_tags(text=response)


async def handle_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle incoming text messages."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.effective_user or not update.message or not update.message.text:
        return

    if not check_authorized(update.effective_user.id, allowed_user_id=settings.telegram_user_id):
        await update.message.reply_text("This bot is private.")
        return

    logger.info(f"Text from {update.effective_user.id}: {update.message.text[:50]}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    memory: list[str] = context.bot_data.get("memory", [])
    memory_section = _get_memory_section(settings=settings, memory=memory)
    prompt = build_prompt(user_message=update.message.text, memory_section=memory_section)
    response, new_session_id = await call_claude(
        prompt=prompt,
        claude_path=settings.claude_path,
        session_id=session.get("session_id"),
        resume=True,
    )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(response=response, settings=settings, context=context)
    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)


async def handle_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle incoming photos."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.effective_user or not update.message or not update.message.photo:
        return

    if not check_authorized(update.effective_user.id, allowed_user_id=settings.telegram_user_id):
        await update.message.reply_text("This bot is private.")
        return

    logger.info(f"Photo from {update.effective_user.id}")
    await update.message.chat.send_action(action=ChatAction.TYPING)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_path = settings.uploads_dir / f"image_{update.message.message_id}.jpg"
    await file.download_to_drive(custom_path=str(file_path))

    caption = update.message.caption or "Analyze this image."
    memory: list[str] = context.bot_data.get("memory", [])
    memory_section = _get_memory_section(settings=settings, memory=memory)
    prompt = build_prompt(user_message=f"[Image: {file_path}]\n\n{caption}", memory_section=memory_section)
    response, new_session_id = await call_claude(
        prompt=prompt,
        claude_path=settings.claude_path,
        session_id=session.get("session_id"),
        resume=True,
        add_dirs=[str(settings.uploads_dir)],
    )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(response=response, settings=settings, context=context)
    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)

    with contextlib.suppress(OSError):
        os.unlink(file_path)


async def handle_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle incoming documents."""
    settings: Settings = context.bot_data["settings"]
    session: dict = context.bot_data["session"]

    if not update.effective_user or not update.message or not update.message.document:
        return

    if not check_authorized(update.effective_user.id, allowed_user_id=settings.telegram_user_id):
        await update.message.reply_text("This bot is private.")
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
    memory_section = _get_memory_section(settings=settings, memory=memory)
    prompt = build_prompt(user_message=f"[File: {file_path}]\n\n{caption}", memory_section=memory_section)
    response, new_session_id = await call_claude(
        prompt=prompt,
        claude_path=settings.claude_path,
        session_id=session.get("session_id"),
        resume=True,
        add_dirs=[str(settings.uploads_dir)],
    )

    if new_session_id:
        session["session_id"] = new_session_id
    save_session(
        session_file=settings.session_file,
        session_id=session.get("session_id"),
    )

    response = _process_memory_response(response=response, settings=settings, context=context)
    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)

    with contextlib.suppress(OSError):
        os.unlink(file_path)
