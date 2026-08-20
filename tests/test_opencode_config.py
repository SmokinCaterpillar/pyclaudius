import json
import stat

import pytest

from pyclaudius.config import Settings
from pyclaudius.opencode_config import (
    COMPACTION_RESERVED_TOKENS,
    build_opencode_config,
    build_permission_map,
    write_opencode_config,
)


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("RELAY_DIR", str(tmp_path / "relay"))
    monkeypatch.setenv("TENSORX_API_KEY", "sk-test")
    monkeypatch.delenv("ALLOWED_TOOLS", raising=False)
    return Settings()


def test_permission_map_has_no_ask_entries(settings):
    """An "ask" would block forever: runs happen with no TTY attached."""
    permission = build_permission_map(settings=settings, mcp_tool_names=[])
    assert "ask" not in permission.values()


def test_permission_map_allows_builtin_tools(settings):
    permission = build_permission_map(settings=settings, mcp_tool_names=[])
    for tool in ("read", "edit", "bash", "glob", "grep", "list"):
        assert permission[tool] == "allow"


def test_permission_map_has_no_write_key(settings):
    """There is no "write" permission in opencode — writes fall under "edit"."""
    assert "write" not in build_permission_map(settings=settings, mcp_tool_names=[])


def test_permission_map_denies_out_of_scope_tools(settings):
    permission = build_permission_map(settings=settings, mcp_tool_names=[])
    for tool in ("webfetch", "websearch", "external_directory", "doom_loop", "task"):
        assert permission[tool] == "deny"


def test_permission_map_allows_mcp_tools(settings):
    permission = build_permission_map(
        settings=settings, mcp_tool_names=["pyclaudius_list_cron_jobs"]
    )
    assert permission["pyclaudius_list_cron_jobs"] == "allow"


def test_permission_map_allows_configured_extra_tools(monkeypatch, settings):
    monkeypatch.setenv("ALLOWED_TOOLS", '["patch"]')
    permission = build_permission_map(settings=Settings(), mcp_tool_names=[])
    assert permission["patch"] == "allow"


def test_config_has_no_provider_block(settings):
    """TensorX comes from opencode's registry; declaring it would risk drift."""
    config = build_opencode_config(settings=settings, mcp_port=1234, mcp_tool_names=[])
    assert "provider" not in config


def test_config_does_not_contain_the_api_key(settings):
    """The key travels in the subprocess env so it never lands on disk."""
    config = build_opencode_config(settings=settings, mcp_port=1234, mcp_tool_names=[])
    assert "sk-test" not in json.dumps(config)


def test_config_sets_model(settings):
    config = build_opencode_config(settings=settings, mcp_port=1234, mcp_tool_names=[])
    assert config["model"] == settings.opencode_model


def test_config_enables_compaction(settings):
    """The reserve is asserted as a concrete figure, not against its own constant.

    opencode has no percentage threshold, so this token buffer is what stands in
    for the Claude CLI's old compact-at-90% behaviour: roughly a tenth of the
    1M-token window. A zero reserve would leave no room to summarize in.
    """
    config = build_opencode_config(settings=settings, mcp_port=1234, mcp_tool_names=[])
    assert config["compaction"] == {
        "auto": True,
        "prune": False,
        "reserved": 100_000,
    }
    assert COMPACTION_RESERVED_TOKENS == 100_000


def test_compaction_reserve_leaves_room_but_not_the_whole_window(settings):
    limit = settings.opencode_context_limit
    assert 0 < COMPACTION_RESERVED_TOKENS < limit // 2


def test_config_injects_mcp_port(settings):
    config = build_opencode_config(settings=settings, mcp_port=54321, mcp_tool_names=[])
    assert config["mcp"]["pyclaudius"] == {
        "type": "remote",
        "url": "http://127.0.0.1:54321/mcp",
        "enabled": True,
        "oauth": False,
    }


def test_config_disables_autoupdate(settings):
    """The install dir is read-only under systemd; a self-update would fail."""
    config = build_opencode_config(settings=settings, mcp_port=1, mcp_tool_names=[])
    assert config["autoupdate"] is False


def test_config_declares_schema(settings):
    config = build_opencode_config(settings=settings, mcp_port=1, mcp_tool_names=[])
    assert config["$schema"] == "https://opencode.ai/config.json"


def test_write_config_is_owner_only(tmp_path):
    path = tmp_path / "opencode.json"
    write_opencode_config(path=path, config={"model": "m"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_config_round_trips(tmp_path):
    path = tmp_path / "opencode.json"
    write_opencode_config(
        path=path, config={"model": "m", "permission": {"bash": "allow"}}
    )
    assert json.loads(path.read_text()) == {
        "model": "m",
        "permission": {"bash": "allow"},
    }


def test_write_config_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "opencode.json"
    write_opencode_config(path=path, config={})
    assert path.exists()


def test_write_config_overwrites_existing(tmp_path):
    path = tmp_path / "opencode.json"
    write_opencode_config(path=path, config={"model": "old"})
    write_opencode_config(path=path, config={"model": "new"})
    assert json.loads(path.read_text())["model"] == "new"
