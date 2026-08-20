"""Invocation of the opencode CLI — the only place a subprocess is spawned."""

import asyncio
import logging
import os
from pathlib import Path
from typing import NotRequired, TypedDict

from pyclaudius.backlog import with_backlog
from pyclaudius.opencode_events import OpencodeResult, parse_opencode_stream

logger = logging.getLogger(__name__)

# Environment variable that activates the TensorX provider from opencode's
# models.dev registry. Supplying it is all that is needed — no provider block.
API_KEY_ENV = "TENSORX_API_KEY"

# opencode session ids look like ``ses_fe591cc9fffeoMveld49fa4stF``. Anything
# else (notably a uuid persisted by an older pyclaudius) is not resumable and
# must not be passed to ``--session``.
SESSION_ID_PREFIX = "ses_"

# Sentinel returncode for failures on our side of the process boundary (timeout,
# exec error) as opposed to a real exit status from opencode.
LOCAL_FAILURE = -1


class RunInfo(TypedDict):
    """Per-call scratch space filled in by :func:`call_opencode`.

    Kept separate from the return value so the ``(response, session_id)``
    contract stays intact for every caller, while ``/context`` still gets at
    token usage and :func:`with_backlog` at structured failure detail.
    """

    result: NotRequired[OpencodeResult]
    tokens: NotRequired[int | None]
    cost: NotRequired[float | None]


def build_subprocess_env(*, api_key: str, config_file: Path | None) -> dict[str, str]:
    """Build a minimal environment for the opencode CLI subprocess.

    Only what opencode genuinely needs is forwarded: HOME and the XDG paths
    (session storage, caches), PATH (to find executables), the config path, and
    the provider API key. Everything else — including TELEGRAM_BOT_TOKEN — is
    stripped so the subprocess cannot leak it.
    """
    env: dict[str, str] = {"NO_COLOR": "1", "TERM": "dumb"}
    for key in ("HOME", "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    if api_key:
        env[API_KEY_ENV] = api_key
    if config_file is not None:
        env["OPENCODE_CONFIG"] = str(config_file)
    return env


def is_resumable_session(*, session_id: str | None) -> bool:
    """Check whether *session_id* can be passed to ``opencode run --session``."""
    return bool(session_id) and str(session_id).startswith(SESSION_ID_PREFIX)


def _is_stale_session(*, returncode: int, result: OpencodeResult, stderr: str) -> bool:
    """Detect a resume against a session opencode no longer knows about.

    An unknown session id does not produce a JSON ``error`` event: opencode
    exits non-zero with *empty stdout* and prints ``Error: Session not found``
    as plain text on stderr. The second arm catches a non-zero exit that
    emitted no events at all — retrying without ``--session`` is harmless
    there. A genuine API error (an ``error`` event) is not stale, and neither
    is a local failure such as a timeout, which reports ``returncode`` as
    ``LOCAL_FAILURE`` and must never be retried automatically.
    """
    if "session not found" in stderr.lower():
        return True
    if returncode <= 0:
        return False
    return not result.text and result.error_name is None


def _format_failure(*, result: OpencodeResult) -> str:
    """Render an error event as the user-visible response string."""
    parts = [result.error_name or "Error"]
    if result.status_code is not None:
        parts[0] = f"{parts[0]} ({result.status_code})"
    if result.error_message:
        parts.append(result.error_message)
    return "Error: " + ": ".join(parts)


async def _spawn_opencode(
    *,
    prompt: str,
    opencode_path: str,
    api_key: str,
    session_id: str | None,
    model: str | None,
    files: list[str] | None,
    cwd: str | None,
    config_file: Path | None,
    auto_approve: bool,
    timeout: int,
) -> tuple[str, OpencodeResult, int, str]:
    """Spawn opencode once.

    Returns (response_or_error, parsed_result, returncode, stderr_text).
    """
    args = [
        opencode_path,
        "run",
        "--format",
        "json",
        "--log-level",
        "ERROR",
        "--pure",
    ]

    if model:
        args.extend(["--model", model])

    if is_resumable_session(session_id=session_id):
        args.extend(["--session", str(session_id)])

    # Attaching beats naming a path in the prompt: it hands the file to the
    # model directly (images included) instead of hoping it reaches for `read`.
    for path in files or []:
        args.extend(["--file", path])

    # "--" ends option parsing. Without it `--file` (an array option) swallows
    # the prompt as another filename, and a prompt starting with "-" prints the
    # usage screen instead of running. Both verified against opencode 1.18.18.
    args.append("--")

    if auto_approve:
        args.append("--auto")

    args.append(prompt)

    logger.info(f"Calling opencode (session={session_id}): {prompt[:50]}...")
    logger.info(f"Full command: {' '.join([*args[:-1], '<prompt>'])}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=build_subprocess_env(api_key=api_key, config_file=config_file),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        empty = parse_opencode_stream(stdout="")
        return (
            f"Error: opencode timed out after {timeout}s",
            empty,
            LOCAL_FAILURE,
            "",
        )
    except OSError as e:
        empty = parse_opencode_stream(stdout="")
        return f"Error: Could not run opencode: {e}", empty, LOCAL_FAILURE, ""

    stdout_text = stdout.decode()
    stderr_text = stderr.decode()
    returncode = proc.returncode if proc.returncode is not None else 0

    result = parse_opencode_stream(stdout=stdout_text)

    if result.error_name is not None:
        logger.warning(
            f"opencode error event: {result.error_name}"
            f" (status={result.status_code}, retryable={result.is_retryable})"
        )
        return _format_failure(result=result), result, returncode, stderr_text

    if result.text:
        if not result.finished:
            logger.warning(
                "opencode produced text but no terminal step_finish"
                f" (rc={returncode}, session={result.session_id})"
            )
        return result.text, result, returncode, stderr_text

    if returncode != 0:
        error_msg = stderr_text.strip() or f"opencode exited with code {returncode}"
        return f"Error: {error_msg}", result, returncode, stderr_text

    logger.warning(
        f"opencode returned no text (rc={returncode}, session={result.session_id},"
        f" stdout_bytes={len(stdout)}, stderr_bytes={len(stderr)})"
    )
    return "", result, returncode, stderr_text


@with_backlog
async def call_opencode(
    *,
    prompt: str,
    opencode_path: str = "opencode",
    api_key: str = "",
    session_id: str | None = None,
    resume: bool = False,
    model: str | None = None,
    files: list[str] | None = None,
    cwd: str | None = None,
    config_file: Path | None = None,
    auto_approve: bool = False,
    timeout: int = 300,
    run_info: RunInfo | None = None,
) -> tuple[str, str | None]:
    """Spawn the opencode CLI and return (response_text, session_id).

    opencode mints its own session ids, so the first call passes no
    ``--session`` and the id is harvested from the event stream; later calls
    resume with ``--session``. A resume against a session opencode has
    forgotten is retried once as a fresh session, so the user does not have to
    issue /clear.
    """
    resume_id = session_id if resume else None

    response, result, returncode, stderr_text = await _spawn_opencode(
        prompt=prompt,
        opencode_path=opencode_path,
        api_key=api_key,
        session_id=resume_id,
        model=model,
        files=files,
        cwd=cwd,
        config_file=config_file,
        auto_approve=auto_approve,
        timeout=timeout,
    )

    if is_resumable_session(session_id=resume_id) and _is_stale_session(
        returncode=returncode, result=result, stderr=stderr_text
    ):
        logger.warning(f"Stale session {resume_id}, retrying as a fresh session")
        response, result, returncode, stderr_text = await _spawn_opencode(
            prompt=prompt,
            opencode_path=opencode_path,
            api_key=api_key,
            session_id=None,
            model=model,
            files=files,
            cwd=cwd,
            config_file=config_file,
            auto_approve=auto_approve,
            timeout=timeout,
        )

    if run_info is not None:
        run_info["result"] = result
        run_info["tokens"] = result.tokens
        run_info["cost"] = result.cost

    return response, result.session_id
