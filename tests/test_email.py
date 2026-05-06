"""Tests for pyclaudius.mcp_tools.email — IMAP logic."""

import email as email_mod
import email.policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

from pyclaudius.mcp_tools.email import (
    _extract_body,
    _extract_original_sender,
    _sanitize_subject,
    _strip_html_tags,
    _unique_path,
    delete_read_mail,
    download_new_mail,
)

# --- _sanitize_subject ---


def test_sanitize_subject_basic():
    assert _sanitize_subject(subject="Hello World") == "Hello_World"


def test_sanitize_subject_special_chars():
    assert _sanitize_subject(subject="Re: FW: Test!@#$%") == "Re_FW_Test"


def test_sanitize_subject_truncation():
    long_subject = "A" * 100
    result = _sanitize_subject(subject=long_subject, max_length=80)
    assert len(result) == 80


def test_sanitize_subject_empty():
    assert _sanitize_subject(subject="") == ""


# --- _strip_html_tags ---


def test_strip_html_tags():
    assert _strip_html_tags(html="<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_tags_no_tags():
    assert _strip_html_tags(html="plain text") == "plain text"


# --- _extract_body ---


def test_extract_body_plain_text():
    msg = MIMEText("Hello plain", "plain")
    parsed = email_mod.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    assert "Hello plain" in _extract_body(msg=parsed)


def test_extract_body_html_only():
    msg = MIMEText("<p>Hello HTML</p>", "html")
    parsed = email_mod.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    result = _extract_body(msg=parsed)
    assert "Hello HTML" in result
    assert "<p>" not in result


def test_extract_body_multipart_prefers_plain():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("Plain body", "plain"))
    msg.attach(MIMEText("<p>HTML body</p>", "html"))
    parsed = email_mod.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    result = _extract_body(msg=parsed)
    assert "Plain body" in result


def test_extract_body_multipart_html_fallback():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<p>HTML only</p>", "html"))
    parsed = email_mod.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    result = _extract_body(msg=parsed)
    assert "HTML only" in result
    assert "<p>" not in result


# --- _unique_path ---


def test_unique_path_no_conflict(tmp_path):
    path = tmp_path / "test.md"
    assert _unique_path(path=path) == path


def test_unique_path_with_conflict(tmp_path):
    path = tmp_path / "test.md"
    path.write_text("exists")
    result = _unique_path(path=path)
    assert result == tmp_path / "test_2.md"


def test_unique_path_multiple_conflicts(tmp_path):
    (tmp_path / "test.md").write_text("exists")
    (tmp_path / "test_2.md").write_text("exists")
    result = _unique_path(path=tmp_path / "test.md")
    assert result == tmp_path / "test_3.md"


# --- _extract_original_sender ---


def _parse(raw: bytes):
    return email_mod.message_from_bytes(raw, policy=email.policy.default)


def test_extract_original_sender_x_original_from_header():
    msg = _parse(
        _build_raw_email(extra_headers={"X-Original-From": "orig@example.com"})
    )
    assert _extract_original_sender(msg=msg, body="") == "orig@example.com"


def test_extract_original_sender_resent_from_header():
    msg = _parse(_build_raw_email(extra_headers={"Resent-From": "resent@example.com"}))
    assert _extract_original_sender(msg=msg, body="") == "resent@example.com"


def test_extract_original_sender_x_original_sender_header():
    msg = _parse(
        _build_raw_email(extra_headers={"X-Original-Sender": "xorig@example.com"})
    )
    assert _extract_original_sender(msg=msg, body="") == "xorig@example.com"


def test_extract_original_sender_gmail_marker():
    msg = _parse(_build_raw_email())
    body = (
        "Some intro\n"
        "\n"
        "---------- Forwarded message ---------\n"
        "From: Original Person <orig@example.com>\n"
        "Date: Mon, 01 Jan 2024 09:00:00 +0000\n"
        "Subject: Hello\n"
        "\n"
        "Body content\n"
    )
    assert (
        _extract_original_sender(msg=msg, body=body)
        == "Original Person <orig@example.com>"
    )


def test_extract_original_sender_outlook_marker():
    msg = _parse(_build_raw_email())
    body = (
        "-----Original Message-----\n"
        "From: orig@outlook.com\n"
        "Sent: Monday\n"
        "To: me@example.com\n"
    )
    assert _extract_original_sender(msg=msg, body=body) == "orig@outlook.com"


def test_extract_original_sender_apple_marker():
    msg = _parse(_build_raw_email())
    body = "Hi all,\n\nBegin forwarded message:\n\nFrom: orig@apple.com\nDate: ...\n"
    assert _extract_original_sender(msg=msg, body=body) == "orig@apple.com"


def test_extract_original_sender_no_match():
    msg = _parse(_build_raw_email())
    assert _extract_original_sender(msg=msg, body="just regular text") is None


def test_extract_original_sender_ignores_from_outside_marker():
    """A bare 'From:' line in a non-forwarded body must not be mistaken for the original sender."""
    msg = _parse(_build_raw_email())
    body = "Quoting yesterday's chat:\nFrom: somebody@example.com (but not a forward)\n"
    assert _extract_original_sender(msg=msg, body=body) is None


def test_extract_original_sender_header_takes_precedence_over_body():
    msg = _parse(
        _build_raw_email(extra_headers={"X-Original-From": "header@example.com"})
    )
    body = "---------- Forwarded message ---------\nFrom: body@example.com\n"
    assert _extract_original_sender(msg=msg, body=body) == "header@example.com"


# --- download_new_mail ---


def _build_raw_email(
    *,
    subject: str = "Test Subject",
    from_addr: str = "sender@example.com",
    date: str = "Mon, 01 Jan 2024 12:00:00 +0000",
    body: str = "Hello body",
    forwarded_to: str | None = None,
    delivered_to: str | None = None,
    html_body: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    """Build a raw RFC822 email as bytes for testing."""
    if html_body is not None:
        msg = MIMEMultipart("alternative")
        if body:
            msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body, "plain")

    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date
    if forwarded_to:
        msg["X-Forwarded-To"] = forwarded_to
    if delivered_to:
        msg["Delivered-To"] = delivered_to
    if extra_headers:
        for key, value in extra_headers.items():
            msg[key] = value
    return msg.as_bytes()


def _mock_imap(*, raw_emails: list[bytes]):
    """Create a mock IMAP4_SSL instance that returns given emails."""
    mock_conn = MagicMock()
    mock_conn.login.return_value = ("OK", [b"Logged in"])
    mock_conn.select.return_value = ("OK", [b"1"])

    if raw_emails:
        msg_ids = b" ".join(str(i + 1).encode() for i in range(len(raw_emails)))
        mock_conn.search.return_value = ("OK", [msg_ids])
        mock_conn.fetch.side_effect = [
            ("OK", [(b"1 (RFC822 {0})", raw), b")"]) for raw in raw_emails
        ]
    else:
        mock_conn.search.return_value = ("OK", [b""])
        mock_conn.fetch.side_effect = []

    mock_conn.store.return_value = ("OK", [b""])
    mock_conn.logout.return_value = ("BYE", [b"Logging out"])
    return mock_conn


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_no_new_mail(mock_imap_cls, tmp_path):
    mock_conn = _mock_imap(raw_emails=[])
    mock_imap_cls.return_value = mock_conn

    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(tmp_path / "emails"),
    )

    assert result == []
    mock_conn.login.assert_called_once_with(user="user@example.com", password="secret")


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_single_mail(mock_imap_cls, tmp_path):
    raw = _build_raw_email(subject="Test Email", from_addr="alice@example.com")
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    assert len(result) == 1
    assert "Test_Email" in result[0]
    assert result[0].endswith(".md")

    content = (output_dir / result[0]).read_text()
    assert "# Test Email" in content
    assert "alice@example.com" in content
    assert "Hello body" in content


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_multiple_mails(mock_imap_cls, tmp_path):
    emails = [
        _build_raw_email(subject="First", from_addr="a@example.com"),
        _build_raw_email(subject="Second", from_addr="b@example.com"),
    ]
    mock_conn = _mock_imap(raw_emails=emails)
    mock_imap_cls.return_value = mock_conn

    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(tmp_path / "emails"),
    )

    assert len(result) == 2


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_duplicate_subjects(mock_imap_cls, tmp_path):
    emails = [
        _build_raw_email(subject="Same Subject"),
        _build_raw_email(subject="Same Subject"),
    ]
    mock_conn = _mock_imap(raw_emails=emails)
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    assert len(result) == 2
    assert result[0] != result[1]


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_forwarded_header_x_forwarded_to(mock_imap_cls, tmp_path):
    raw = _build_raw_email(
        subject="Forwarded",
        forwarded_to="forward@example.com",
    )
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    content = (output_dir / result[0]).read_text()
    assert "forward@example.com" in content
    assert "**Forwarded to:**" in content


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_forwarded_header_delivered_to(mock_imap_cls, tmp_path):
    raw = _build_raw_email(
        subject="Delivered",
        delivered_to="delivered@example.com",
    )
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    content = (output_dir / result[0]).read_text()
    assert "delivered@example.com" in content


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_writes_original_sender_for_forwarded_mail(mock_imap_cls, tmp_path):
    """When a forwarded email's body has a Gmail-style marker, the markdown should include Original sender."""
    raw = _build_raw_email(
        subject="Forwarded with original",
        from_addr="forwarder@gmail.com",
        forwarded_to="me@example.com",
        body=(
            "FYI\n\n"
            "---------- Forwarded message ---------\n"
            "From: Alice <alice@example.com>\n"
            "Date: Mon, 01 Jan 2024 09:00:00 +0000\n"
            "Subject: Hello\n\n"
            "Original body\n"
        ),
    )
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    content = (output_dir / result[0]).read_text()
    assert "**From:** forwarder@gmail.com" in content
    assert "**Original sender:** Alice <alice@example.com>" in content
    assert "**Forwarded to:** me@example.com" in content


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_omits_original_sender_when_not_forwarded(mock_imap_cls, tmp_path):
    """A normal (non-forwarded) email must not gain an Original sender line."""
    raw = _build_raw_email(
        subject="Plain mail",
        from_addr="alice@example.com",
        body="Just a regular message.",
    )
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    content = (output_dir / result[0]).read_text()
    assert "**Original sender:**" not in content


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_download_html_only_body(mock_imap_cls, tmp_path):
    raw = _build_raw_email(
        subject="HTML Email",
        body="",
        html_body="<p>HTML content here</p>",
    )
    mock_conn = _mock_imap(raw_emails=[raw])
    mock_imap_cls.return_value = mock_conn

    output_dir = tmp_path / "emails"
    result = download_new_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
        output_dir=str(output_dir),
    )

    content = (output_dir / result[0]).read_text()
    assert "HTML content here" in content
    assert "<p>" not in content


# --- delete_read_mail ---


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_delete_no_read_mail(mock_imap_cls):
    mock_conn = MagicMock()
    mock_conn.login.return_value = ("OK", [b"Logged in"])
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.search.return_value = ("OK", [b""])
    mock_conn.logout.return_value = ("BYE", [b"Logging out"])
    mock_imap_cls.return_value = mock_conn

    count = delete_read_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
    )

    assert count == 0
    mock_conn.expunge.assert_not_called()


@patch("pyclaudius.mcp_tools.email.imaplib.IMAP4_SSL")
def test_delete_read_mail_success(mock_imap_cls):
    mock_conn = MagicMock()
    mock_conn.login.return_value = ("OK", [b"Logged in"])
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.search.return_value = ("OK", [b"1 2 3"])
    mock_conn.store.return_value = ("OK", [b""])
    mock_conn.expunge.return_value = ("OK", [b""])
    mock_conn.logout.return_value = ("BYE", [b"Logging out"])
    mock_imap_cls.return_value = mock_conn

    count = delete_read_mail(
        imap_host="imap.example.com",
        imap_port=993,
        email_user="user@example.com",
        email_password="secret",
    )

    assert count == 3
    assert mock_conn.store.call_count == 3
    mock_conn.expunge.assert_called_once()
