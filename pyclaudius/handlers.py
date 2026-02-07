import contextlib
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pyclaudius.claude import call_claude
from pyclaudius.config import Settings
from pyclaudius.prompt import build_prompt
from pyclaudius.response import split_response
from pyclaudius.session import save_session

logger = logging.getLogger(__name__)


def check_authorized(user_id: int, *, allowed_user_id: str) -> bool:
    """Check if a Telegram user ID is authorized."""
    return str(user_id) == allowed_user_id


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

    prompt = build_prompt(user_message=update.message.text)
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
    prompt = build_prompt(user_message=f"[Image: {file_path}]\n\n{caption}")
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
    prompt = build_prompt(user_message=f"[File: {file_path}]\n\n{caption}")
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

    for chunk in split_response(text=response):
        await update.message.reply_text(chunk)

    with contextlib.suppress(OSError):
        os.unlink(file_path)
