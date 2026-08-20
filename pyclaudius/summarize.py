"""Manual context compaction via a short-lived opencode server.

``opencode run`` has no compact command — compaction is otherwise automatic,
driven by the ``compaction`` block in the generated config. The only manual
trigger is the server API, so ``/compact`` starts an opencode server on a free
local port, asks it to summarize the current session, and shuts it down again.

Sessions live on disk, so a fresh server can summarize a session created by
earlier ``opencode run`` invocations. Summarizing keeps the same session id, and
resuming afterwards still sees the pre-compaction history as a summary.
"""

import asyncio
import logging

import httpx

from pyclaudius.config import Settings
from pyclaudius.mcp_tools.config import find_free_port
from pyclaudius.opencode import build_subprocess_env

logger = logging.getLogger(__name__)

SERVER_HOST = "127.0.0.1"
_STARTUP_TIMEOUT_SECONDS = 30.0
_STARTUP_POLL_SECONDS = 0.5
_SHUTDOWN_TIMEOUT_SECONDS = 10.0
_VERIFY_ATTEMPTS = 3
_VERIFY_POLL_SECONDS = 1.0


async def wait_for_server(
    *,
    base_url: str,
    client: httpx.AsyncClient,
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> bool:
    """Poll the server's session listing until it answers, or time out."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get(f"{base_url}/session", timeout=5.0)
        except httpx.HTTPError:
            await asyncio.sleep(_STARTUP_POLL_SECONDS)
            continue
        if response.status_code == httpx.codes.OK:
            return True
        await asyncio.sleep(_STARTUP_POLL_SECONDS)
    return False


async def request_summarize(
    *,
    base_url: str,
    session_id: str,
    provider_id: str,
    model_id: str,
    client: httpx.AsyncClient,
    timeout: float,
) -> tuple[bool, str]:
    """POST the summarize request. Returns (succeeded, detail).

    ``providerID`` and ``modelID`` are both mandatory — an empty body is
    rejected with ``400 Missing key at ["providerID"]``.
    """
    try:
        response = await client.post(
            f"{base_url}/session/{session_id}/summarize",
            json={"providerID": provider_id, "modelID": model_id},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        return False, f"request failed: {e}"

    if response.status_code != httpx.codes.OK:
        return False, f"HTTP {response.status_code}: {response.text[:200]}"
    return True, response.text[:200]


def _reply_to_compaction(*, messages: object) -> dict | None:
    """Return the assistant message that answers the newest compaction request.

    Anchored to the compaction part rather than simply taking the last
    assistant message: the summarize POST can return before its reply is
    recorded, and an *earlier* turn's clean reply would then read as success.
    """
    if not isinstance(messages, list):
        return None

    compaction_at = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        parts = message.get("parts") or []
        if any(
            isinstance(part, dict) and part.get("type") == "compaction"
            for part in parts
        ):
            compaction_at = index

    if compaction_at is None:
        return None

    for message in messages[compaction_at + 1 :]:
        info = message.get("info", {}) if isinstance(message, dict) else {}
        if info.get("role") == "assistant":
            return info
    return None


async def read_compaction_error(
    *,
    base_url: str,
    session_id: str,
    client: httpx.AsyncClient,
    attempts: int = _VERIFY_ATTEMPTS,
) -> tuple[bool, str | None]:
    """Read the session back to find out whether compaction actually worked.

    A 200 from the summarize endpoint only means the request was accepted: with
    a dead API key it still answers ``true`` and still appends the compaction
    part, while the assistant message that should hold the summary carries an
    ``error`` instead. Verified against opencode 1.18.18 — without this check
    ``/compact`` would report success for a compaction that never happened.

    Returns (confirmed, error_detail). ``confirmed`` is False when the session
    could not be read at all, in which case nothing is claimed either way.
    """
    for attempt in range(attempts):
        try:
            response = await client.get(
                f"{base_url}/session/{session_id}/message", timeout=15.0
            )
            messages = response.json()
        except (httpx.HTTPError, ValueError):
            return False, None

        reply = _reply_to_compaction(messages=messages)
        if reply is not None:
            error = reply.get("error")
            if not error:
                return True, None
            data = error.get("data", {}) if isinstance(error, dict) else {}
            status = data.get("statusCode")
            name = error.get("name", "Error") if isinstance(error, dict) else "Error"
            detail = f"{name} ({status})" if status else str(name)
            message_text = data.get("message")
            return True, f"{detail}: {message_text}" if message_text else detail

        # The assistant reply may not have landed yet; give it a moment.
        if attempt < attempts - 1:
            await asyncio.sleep(_VERIFY_POLL_SECONDS)
    return False, None


async def _terminate(*, proc: asyncio.subprocess.Process) -> None:
    """Stop the server, escalating to SIGKILL if it lingers."""
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("opencode server did not exit on SIGTERM, killing it")
        proc.kill()
        await proc.wait()


async def compact_session(*, settings: Settings, session_id: str) -> str:
    """Compact *session_id* and return a user-facing status message."""
    port = find_free_port()
    base_url = f"http://{SERVER_HOST}:{port}"

    try:
        proc = await asyncio.create_subprocess_exec(
            settings.opencode_path,
            "serve",
            "--port",
            str(port),
            "--hostname",
            SERVER_HOST,
            stdin=asyncio.subprocess.DEVNULL,
            # Discarded rather than piped: nothing reads these while the server
            # runs, and a full pipe buffer would block it mid-request. If it
            # fails to come up, the exit status below is the diagnostic.
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(settings.opencode_work_dir),
            env=build_subprocess_env(
                api_key=settings.tensorx_api_key,
                config_file=settings.opencode_config_file,
            ),
        )
    except OSError as e:
        return f"Could not start opencode server: {e}"

    logger.info(f"Started opencode server on port {port} for /compact")
    try:
        async with httpx.AsyncClient() as client:
            if not await wait_for_server(base_url=base_url, client=client):
                if proc.returncode is not None:
                    return (
                        "opencode server exited immediately"
                        f" (status {proc.returncode})."
                    )
                return "opencode server did not become ready in time."

            succeeded, detail = await request_summarize(
                base_url=base_url,
                session_id=session_id,
                provider_id=settings.provider_id,
                model_id=settings.model_id,
                client=client,
                timeout=float(settings.opencode_timeout),
            )
            confirmed, error_detail = (False, None)
            if succeeded:
                confirmed, error_detail = await read_compaction_error(
                    base_url=base_url, session_id=session_id, client=client
                )
    finally:
        await _terminate(proc=proc)
        logger.info("Stopped opencode server after /compact")

    if not succeeded:
        logger.warning(f"Compaction failed: {detail}")
        return f"Compaction failed — {detail}"
    if error_detail is not None:
        logger.warning(f"Compaction rejected by the provider: {error_detail}")
        return f"Compaction failed — {error_detail}"
    if not confirmed:
        logger.warning("Compaction result could not be confirmed")
        return "Compaction requested, but the result could not be confirmed."
    return "Context compacted. The conversation continues with a summary."
