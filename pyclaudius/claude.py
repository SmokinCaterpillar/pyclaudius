import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


async def call_claude(
    *,
    prompt: str,
    claude_path: str = "claude",
    session_id: str | None = None,
    resume: bool = False,
    add_dirs: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
) -> tuple[str, str | None]:
    """Spawn the Claude CLI and return (response_text, session_id).

    On the first call (no session_id), generates a UUID and passes
    --session-id to start a new session. On subsequent calls, passes
    --resume to continue the conversation.
    """
    args = [claude_path, "-p", prompt, "--output-format", "text"]

    if resume and session_id:
        args.extend(["--resume", session_id])
    elif not session_id:
        session_id = str(uuid.uuid4())
        args.extend(["--session-id", session_id])

    for directory in add_dirs or []:
        args.extend(["--add-dir", directory])

    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    logger.info(f"Calling Claude: {prompt[:50]}...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return "Error: Could not run Claude CLI", None

    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode != 0:
        if stdout_text.strip():
            logger.warning(f"Claude exited with code {proc.returncode} but produced output")
            return stdout_text.strip(), session_id
        error_msg = stderr_text.strip() or f"Claude exited with code {proc.returncode}"
        return f"Error: {error_msg}", None

    return stdout_text.strip(), session_id
