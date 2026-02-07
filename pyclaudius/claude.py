import asyncio
import logging

from pyclaudius.session import extract_session_id

logger = logging.getLogger(__name__)


async def call_claude(
    *,
    prompt: str,
    claude_path: str = "claude",
    session_id: str | None = None,
    resume: bool = False,
    add_dirs: list[str] | None = None,
) -> tuple[str, str | None]:
    """Spawn the Claude CLI and return (response_text, new_session_id)."""
    args = [claude_path, "-p", prompt, "--output-format", "text"]
    if resume and session_id:
        args.extend(["--resume", session_id])
    for directory in add_dirs or []:
        args.extend(["--add-dir", directory])

    logger.info(f"Calling Claude: {prompt[:50]}...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return "Error: Could not run Claude CLI", None

    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode != 0:
        error_msg = stderr_text.strip() or f"Claude exited with code {proc.returncode}"
        return f"Error: {error_msg}", None

    new_session_id = extract_session_id(output=stderr_text)
    return stdout_text.strip(), new_session_id
