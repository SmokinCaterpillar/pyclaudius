import asyncio
import logging
import os
import uuid

from pyclaudius.backlog import with_backlog

logger = logging.getLogger(__name__)


def _build_subprocess_env() -> dict[str, str]:
    """Build a minimal environment for the Claude CLI subprocess.

    Only HOME (needed for ~/.claude/ auth) and PATH (needed to find
    executables) are forwarded.  Everything else — including secrets
    like TELEGRAM_BOT_TOKEN — is stripped so the subprocess cannot
    leak them.
    """
    # Auto-compact the Claude CLI context at 90% capacity (default is 95%).
    # See: https://docs.anthropic.com/en/docs/claude-code
    env: dict[str, str] = {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "90"}
    for key in ("HOME", "PATH"):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


def _is_stale_session(*, response: str) -> bool:
    """Detect a stale-session failure from Claude CLI output.

    Two failure modes when --resume references a session id that Claude
    CLI no longer knows about:
    - Plain-text error 'No conversation found with session ID: ...'.
    - Silent exit with rc=0, empty stdout and empty stderr (response is
      returned as an empty string by ``_spawn_claude``).
    """
    if not response.strip():
        return True
    return "no conversation found with session id" in response.lower()


async def _spawn_claude(
    *,
    prompt: str,
    claude_path: str,
    session_id: str,
    resume: bool,
    add_dirs: list[str] | None,
    allowed_tools: list[str] | None,
    cwd: str | None,
    timeout: int,
) -> tuple[str, str | None]:
    """Spawn Claude CLI once and return (response_or_error, session_id_or_none)."""
    args = [claude_path, "-p", prompt, "--output-format", "text"]

    if resume:
        args.extend(["--resume", session_id])
    else:
        args.extend(["--session-id", session_id])

    for directory in add_dirs or []:
        args.extend(["--add-dir", directory])

    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    logger.info(f"Calling Claude (session={session_id}): {prompt[:50]}...")
    logger.info(f"Full command: {' '.join([*args[:2], '<prompt>', *args[3:]])}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_build_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: Claude CLI timed out after {timeout}s", None
    except OSError as e:
        return f"Error: Could not run Claude CLI: {e}", None

    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode != 0:
        if stdout_text.strip():
            logger.warning(
                f"Claude exited with code {proc.returncode} but produced output"
            )
            return stdout_text.strip(), session_id
        error_msg = stderr_text.strip() or f"Claude exited with code {proc.returncode}"
        return f"Error: {error_msg}", None

    if not stdout_text.strip():
        if stderr_text.strip():
            logger.warning(
                f"Claude returned empty stdout, stderr: {stderr_text.strip()[:200]}"
            )
            return f"Error: {stderr_text.strip()}", None
        logger.warning(
            f"Claude returned empty response"
            f" (rc={proc.returncode}, session={session_id},"
            f" stdout_bytes={len(stdout)}, stderr_bytes={len(stderr)})"
        )

    return stdout_text.strip(), session_id


@with_backlog
async def call_claude(
    *,
    prompt: str,
    claude_path: str = "claude",
    session_id: str | None = None,
    resume: bool = False,
    add_dirs: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
    timeout: int = 300,
) -> tuple[str, str | None]:
    """Spawn the Claude CLI and return (response_text, session_id).

    On the first call (no session_id), generates a UUID and passes
    --session-id to start a new session. On subsequent calls, passes
    --resume to continue the conversation.

    If a --resume call hits a stale session (Claude CLI either prints
    'No conversation found with session ID: ...' or exits silently with
    rc=0 and empty output), the call is retried once with a freshly
    generated session id so the user does not have to issue /clear.
    """
    is_resume = resume and session_id is not None
    if not session_id:
        session_id = str(uuid.uuid4())

    response, used_session = await _spawn_claude(
        prompt=prompt,
        claude_path=claude_path,
        session_id=session_id,
        resume=is_resume,
        add_dirs=add_dirs,
        allowed_tools=allowed_tools,
        cwd=cwd,
        timeout=timeout,
    )

    if is_resume and _is_stale_session(response=response):
        fresh_id = str(uuid.uuid4())
        logger.warning(
            f"Stale session {session_id}, retrying with fresh session {fresh_id}"
        )
        response, used_session = await _spawn_claude(
            prompt=prompt,
            claude_path=claude_path,
            session_id=fresh_id,
            resume=False,
            add_dirs=add_dirs,
            allowed_tools=allowed_tools,
            cwd=cwd,
            timeout=timeout,
        )

    return response, used_session
