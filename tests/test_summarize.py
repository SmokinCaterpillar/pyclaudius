from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pyclaudius.config import Settings
from pyclaudius.summarize import (
    compact_session,
    read_compaction_error,
    request_summarize,
    wait_for_server,
)

SESSION = "ses_fe591cc9fffeoMveld49fa4stF"


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("RELAY_DIR", str(tmp_path / "relay"))
    monkeypatch.setenv("TENSORX_API_KEY", "sk-test")
    return Settings()


def _client(*, get=None, post=None) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(side_effect=get) if get else AsyncMock()
    client.post = AsyncMock(side_effect=post) if post else AsyncMock()
    return client


def _response(status: int, text: str = "true", json_body=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.json = MagicMock(return_value=json_body)
    return response


def _messages(*, error: dict | None = None) -> MagicMock:
    """Build a message list ending in the compaction's assistant reply."""
    info: dict = {"role": "assistant"}
    if error is not None:
        info["error"] = error
    return _response(
        200,
        json_body=[
            {"info": {"role": "user"}, "parts": [{"type": "compaction"}]},
            {"info": info, "parts": [{"type": "text", "text": "summary"}]},
        ],
    )


AUTH_ERROR = {
    "name": "APIError",
    "data": {"message": "Invalid API key or unauthorised access.", "statusCode": 401},
}


# --- readiness polling ---------------------------------------------------


async def test_wait_for_server_returns_true_when_ready():
    client = _client(get=[_response(200)])
    assert await wait_for_server(base_url="http://h:1", client=client) is True


async def test_wait_for_server_retries_until_ready():
    client = _client(get=[httpx.ConnectError("refused"), _response(200)])
    with patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock):
        assert await wait_for_server(base_url="http://h:1", client=client) is True
    assert client.get.await_count == 2


async def test_wait_for_server_times_out():
    client = _client(get=httpx.ConnectError("refused"))
    with patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock):
        assert (
            await wait_for_server(base_url="http://h:1", client=client, timeout=0.0)
            is False
        )


# --- summarize request ---------------------------------------------------


async def test_request_summarize_sends_provider_and_model():
    """Both keys are mandatory — an empty body is rejected with HTTP 400."""
    client = _client(post=[_response(200)])
    succeeded, _ = await request_summarize(
        base_url="http://h:1",
        session_id=SESSION,
        provider_id="tensorx",
        model_id="moonshotai/kimi-k3",
        client=client,
        timeout=30.0,
    )
    assert succeeded is True
    assert client.post.await_args[0][0] == f"http://h:1/session/{SESSION}/summarize"
    assert client.post.await_args[1]["json"] == {
        "providerID": "tensorx",
        "modelID": "moonshotai/kimi-k3",
    }


async def test_request_summarize_reports_http_error():
    client = _client(post=[_response(400, '{"name":"BadRequest"}')])
    succeeded, detail = await request_summarize(
        base_url="http://h:1",
        session_id=SESSION,
        provider_id="tensorx",
        model_id="m",
        client=client,
        timeout=30.0,
    )
    assert succeeded is False
    assert "HTTP 400" in detail


async def test_request_summarize_reports_transport_error():
    client = _client(post=httpx.ReadTimeout("too slow"))
    succeeded, detail = await request_summarize(
        base_url="http://h:1",
        session_id=SESSION,
        provider_id="tensorx",
        model_id="m",
        client=client,
        timeout=1.0,
    )
    assert succeeded is False
    assert "request failed" in detail


# --- full compaction ----------------------------------------------------


def _patch_client(client: MagicMock):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("pyclaudius.summarize.httpx.AsyncClient", return_value=ctx)


@pytest.fixture
def server_process():
    proc = AsyncMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


async def test_compact_session_success(settings, server_process):
    client = _client(get=[_response(200), _messages()], post=[_response(200)])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        message = await compact_session(settings=settings, session_id=SESSION)
    assert "compacted" in message.lower()
    server_process.terminate.assert_called_once()


async def test_compact_session_starts_server_with_config_and_key(
    settings, server_process
):
    client = _client(get=[_response(200), _messages()], post=[_response(200)])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ) as mock_exec,
        _patch_client(client),
    ):
        await compact_session(settings=settings, session_id=SESSION)
    args = mock_exec.call_args[0]
    assert args[1] == "serve"
    assert "--hostname" in args
    env = mock_exec.call_args[1]["env"]
    assert env["TENSORX_API_KEY"] == "sk-test"
    assert env["OPENCODE_CONFIG"] == str(settings.opencode_config_file)


async def test_compact_session_stops_server_even_when_summarize_fails(
    settings, server_process
):
    client = _client(get=[_response(200)], post=[_response(500, "boom")])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        message = await compact_session(settings=settings, session_id=SESSION)
    assert "failed" in message.lower()
    server_process.terminate.assert_called_once()


async def test_compact_session_reports_unready_server(settings, server_process):
    client = _client(get=httpx.ConnectError("refused"))
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
        patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock),
        patch("pyclaudius.summarize.wait_for_server", new_callable=AsyncMock) as ready,
    ):
        ready.return_value = False
        message = await compact_session(settings=settings, session_id=SESSION)
    assert "did not become ready" in message
    server_process.terminate.assert_called_once()


async def test_compact_session_discards_server_output(settings, server_process):
    """Nothing reads these while it runs; a full pipe would block the server."""
    import asyncio as _asyncio

    client = _client(get=[_response(200), _messages()], post=[_response(200)])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ) as mock_exec,
        _patch_client(client),
    ):
        await compact_session(settings=settings, session_id=SESSION)
    assert mock_exec.call_args[1]["stdout"] == _asyncio.subprocess.DEVNULL
    assert mock_exec.call_args[1]["stderr"] == _asyncio.subprocess.DEVNULL


async def test_compact_session_reports_a_server_that_died(settings, server_process):
    server_process.returncode = 3
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(_client()),
        patch("pyclaudius.summarize.wait_for_server", new_callable=AsyncMock) as ready,
    ):
        ready.return_value = False
        message = await compact_session(settings=settings, session_id=SESSION)
    assert "exited immediately" in message
    assert "status 3" in message


async def test_compact_session_handles_missing_binary(settings):
    with patch(
        "pyclaudius.summarize.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("no opencode"),
    ):
        message = await compact_session(settings=settings, session_id=SESSION)
    assert message.startswith("Could not start opencode server")


async def test_compact_session_kills_unresponsive_server(settings, server_process):
    # First wait times out on SIGTERM; the wait after SIGKILL returns.
    server_process.wait = AsyncMock(side_effect=[TimeoutError, None])
    client = _client(get=[_response(200), _messages()], post=[_response(200)])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        await compact_session(settings=settings, session_id=SESSION)
    server_process.kill.assert_called_once()


async def test_compact_session_skips_shutdown_if_already_exited(
    settings, server_process
):
    server_process.returncode = 0
    client = _client(get=[_response(200), _messages()], post=[_response(200)])
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        await compact_session(settings=settings, session_id=SESSION)
    server_process.terminate.assert_not_called()


# --- compaction verification ---------------------------------------------


async def test_read_compaction_error_reports_a_clean_run():
    client = _client(get=[_messages()])
    confirmed, detail = await read_compaction_error(
        base_url="http://h:1", session_id=SESSION, client=client
    )
    assert confirmed is True
    assert detail is None


async def test_read_compaction_error_surfaces_a_provider_error():
    """A 200 from summarize is not proof: the assistant reply holds the failure."""
    client = _client(get=[_messages(error=AUTH_ERROR)])
    confirmed, detail = await read_compaction_error(
        base_url="http://h:1", session_id=SESSION, client=client
    )
    assert confirmed is True
    assert "APIError (401)" in detail
    assert "Invalid API key" in detail


async def test_read_compaction_error_gives_up_when_unreadable():
    client = _client(get=httpx.ConnectError("refused"))
    confirmed, detail = await read_compaction_error(
        base_url="http://h:1", session_id=SESSION, client=client
    )
    assert confirmed is False
    assert detail is None


async def test_read_compaction_error_waits_for_the_assistant_reply():
    """The assistant message may not have landed the instant summarize returns."""
    pending = _response(200, json_body=[{"info": {"role": "user"}, "parts": []}])
    client = _client(get=[pending, _messages()])
    with patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock):
        confirmed, detail = await read_compaction_error(
            base_url="http://h:1", session_id=SESSION, client=client
        )
    assert confirmed is True
    assert detail is None
    assert client.get.await_count == 2


async def test_compact_session_reports_a_failed_summary(settings, server_process):
    client = _client(
        get=[_response(200), _messages(error=AUTH_ERROR)], post=[_response(200)]
    )
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        message = await compact_session(settings=settings, session_id=SESSION)
    assert message.startswith("Compaction failed")
    assert "401" in message


async def test_compact_session_admits_when_it_cannot_confirm(settings, server_process):
    client = _client(
        get=[_response(200), httpx.ConnectError("gone")], post=[_response(200)]
    )
    with (
        patch(
            "pyclaudius.summarize.asyncio.create_subprocess_exec",
            return_value=server_process,
        ),
        _patch_client(client),
    ):
        message = await compact_session(settings=settings, session_id=SESSION)
    assert "could not be confirmed" in message


async def test_read_compaction_error_ignores_replies_before_the_compaction():
    """An earlier clean reply must not be mistaken for the compaction's own."""
    stale = _response(
        200,
        json_body=[
            {"info": {"role": "user"}, "parts": [{"type": "text"}]},
            {"info": {"role": "assistant"}, "parts": [{"type": "text"}]},
            {"info": {"role": "user"}, "parts": [{"type": "compaction"}]},
        ],
    )
    client = _client(get=[stale, stale, _messages(error=AUTH_ERROR)])
    with patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock):
        confirmed, detail = await read_compaction_error(
            base_url="http://h:1", session_id=SESSION, client=client
        )
    assert confirmed is True
    assert "401" in detail


async def test_read_compaction_error_when_no_compaction_was_recorded():
    plain = _response(
        200,
        json_body=[
            {"info": {"role": "user"}, "parts": [{"type": "text"}]},
            {"info": {"role": "assistant"}, "parts": [{"type": "text"}]},
        ],
    )
    client = _client(get=[plain, plain, plain])
    with patch("pyclaudius.summarize.asyncio.sleep", new_callable=AsyncMock):
        confirmed, _ = await read_compaction_error(
            base_url="http://h:1", session_id=SESSION, client=client
        )
    assert confirmed is False
