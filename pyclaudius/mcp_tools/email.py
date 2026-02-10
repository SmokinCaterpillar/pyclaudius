"""IMAP email fetching and cleanup — pure functions, stdlib only."""

import email
import email.policy
import imaplib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_subject(*, subject: str, max_length: int = 80) -> str:
    """Replace non-alphanumeric characters with underscores and truncate."""
    sanitized = re.sub(r"[^a-zA-Z0-9]", "_", subject)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:max_length]


def _strip_html_tags(*, html: str) -> str:
    """Naively strip HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html)


def _extract_body(*, msg: email.message.Message) -> str:
    """Extract body from an email message, preferring text/plain over text/html."""
    if msg.is_multipart():
        text_part: str | None = None
        html_part: str | None = None
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and text_part is None:
                payload = part.get_content()
                if isinstance(payload, str):
                    text_part = payload
            elif content_type == "text/html" and html_part is None:
                payload = part.get_content()
                if isinstance(payload, str):
                    html_part = payload
        if text_part:
            return text_part
        if html_part:
            return _strip_html_tags(html=html_part)
        return ""
    else:
        content_type = msg.get_content_type()
        payload = msg.get_content()
        if not isinstance(payload, str):
            return ""
        if content_type == "text/html":
            return _strip_html_tags(html=payload)
        return payload


def _unique_path(*, path: Path) -> Path:
    """If path exists, append _2, _3, etc. until a free name is found."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def download_new_mail(
    *,
    imap_host: str,
    imap_port: int,
    email_user: str,
    email_password: str,
    output_dir: str | Path,
) -> list[str]:
    """Download unseen emails from IMAP and save as markdown files.

    Returns a list of saved filenames.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_files: list[str] = []

    conn = imaplib.IMAP4_SSL(host=imap_host, port=imap_port)
    try:
        conn.login(user=email_user, password=email_password)
        conn.select("INBOX")

        _status, data = conn.search(None, "UNSEEN")
        message_ids = data[0].split() if data[0] else []

        if not message_ids:
            logger.info("No new unseen emails")
            return saved_files

        for msg_id in message_ids:
            _status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email, policy=email.policy.default)

            subject = str(msg.get("Subject", "No Subject"))
            from_addr = str(msg.get("From", "Unknown"))
            date_str = str(msg.get("Date", "Unknown"))
            forwarded_to = str(
                msg.get("X-Forwarded-To") or msg.get("Delivered-To") or ""
            )

            body = _extract_body(msg=msg)

            # Build date for filename
            date_obj = email.utils.parsedate_to_datetime(date_str) if date_str != "Unknown" else None
            date_suffix = date_obj.strftime("%Y-%m-%d") if date_obj else "unknown"

            sanitized = _sanitize_subject(subject=subject)
            filename = f"email_{sanitized}_{date_suffix}.md"
            file_path = _unique_path(path=output_path / filename)

            # Build markdown content
            lines = [
                f"# {subject}",
                "",
                f"- **From:** {from_addr}",
            ]
            if forwarded_to:
                lines.append(f"- **Forwarded to:** {forwarded_to}")
            lines.extend([
                f"- **Date:** {date_str}",
                "",
                body,
            ])
            file_path.write_text("\n".join(lines), encoding="utf-8")

            conn.store(msg_id, "+FLAGS", "\\Seen")
            saved_files.append(file_path.name)
            logger.info(f"Saved email: {file_path.name}")

    finally:
        conn.logout()

    return saved_files


def delete_read_mail(
    *,
    imap_host: str,
    imap_port: int,
    email_user: str,
    email_password: str,
) -> int:
    """Delete all SEEN emails from the IMAP inbox.

    Returns the number of deleted messages.
    """
    conn = imaplib.IMAP4_SSL(host=imap_host, port=imap_port)
    try:
        conn.login(user=email_user, password=email_password)
        conn.select("INBOX")

        _status, data = conn.search(None, "SEEN")
        message_ids = data[0].split() if data[0] else []

        if not message_ids:
            logger.info("No read emails to delete")
            return 0

        for msg_id in message_ids:
            conn.store(msg_id, "+FLAGS", "\\Deleted")

        conn.expunge()
        count = len(message_ids)
        logger.info(f"Deleted {count} read email(s)")
        return count

    finally:
        conn.logout()
