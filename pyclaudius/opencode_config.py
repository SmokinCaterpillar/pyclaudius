"""Generation of the opencode config file that every CLI run is driven by.

pyclaudius does not use opencode's interactive setup. Instead it writes a
single self-contained config to ``settings.opencode_config_file`` at startup
and points the subprocess at it via ``OPENCODE_CONFIG``. That file carries the
model choice, the compaction policy, the tool-permission map and the MCP server
endpoint (whose port is picked fresh on every start).

Two things are deliberately *not* in it:

- No ``provider`` block. TensorX ships in opencode's models.dev registry with
  correct limits, costs and capabilities; declaring it by hand would only risk
  drifting from upstream. The provider activates from the ``TENSORX_API_KEY``
  environment variable alone.
- No API key. The key travels in the subprocess environment so it never lands
  on disk.
"""

import json
import logging
from pathlib import Path
from typing import Any

from pyclaudius.config import Settings
from pyclaudius.mcp_tools.config import MCP_SERVER_NAME

logger = logging.getLogger(__name__)

# Tools opencode must never reach for in a Telegram relay. ``external_directory``
# and ``doom_loop`` default to "ask", which would block forever without a TTY;
# the rest are simply out of scope for this bot.
_DENIED_TOOLS: tuple[str, ...] = (
    "webfetch",
    "websearch",
    "external_directory",
    "doom_loop",
    "task",
    "skill",
    "question",
)

# Built-in opencode tool permissions granted to every run. Note there is no
# "write" permission in opencode's schema — writes fall under "edit".
_ALLOWED_BUILTIN_TOOLS: tuple[str, ...] = (
    "read",
    "edit",
    "bash",
    "glob",
    "grep",
    "list",
    "todowrite",
)

# Token headroom left free for the compaction pass itself. Roughly 10% of the
# 1M-token window, i.e. the equivalent of the Claude CLI's old
# CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=90.
COMPACTION_RESERVED_TOKENS = 100_000


def build_permission_map(*, settings: Settings, mcp_tool_names: list[str]) -> dict:
    """Build the opencode ``permission`` map.

    Every entry is either ``allow`` or ``deny`` — never ``ask``. A run happens
    with no TTY attached, so an ``ask`` would hang until the timeout instead of
    prompting anybody.
    """
    permission: dict[str, str] = {tool: "allow" for tool in _ALLOWED_BUILTIN_TOOLS}
    for tool in settings.allowed_tools:
        permission[tool] = "allow"
    for tool in mcp_tool_names:
        permission[tool] = "allow"
    for tool in _DENIED_TOOLS:
        permission[tool] = "deny"
    return permission


def build_opencode_config(
    *, settings: Settings, mcp_port: int, mcp_tool_names: list[str]
) -> dict:
    """Build the full opencode config for this process."""
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": settings.opencode_model,
        # The install directory is read-only under the systemd unit's
        # ProtectHome, so a self-update attempt would fail — and a daemon should
        # not replace its own binary mid-flight anyway.
        "autoupdate": False,
        "compaction": {
            "auto": True,
            "prune": False,
            "reserved": COMPACTION_RESERVED_TOKENS,
        },
        "permission": build_permission_map(
            settings=settings, mcp_tool_names=mcp_tool_names
        ),
        "mcp": {
            MCP_SERVER_NAME: {
                "type": "remote",
                "url": f"http://127.0.0.1:{mcp_port}/mcp",
                "enabled": True,
                # The MCP server is local and unauthenticated; skip opencode's
                # OAuth auto-detection probe.
                "oauth": False,
            }
        },
    }
    return config


def write_opencode_config(*, path: Path, config: dict) -> None:
    """Write the opencode config, readable only by the owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    path.chmod(0o600)
    logger.info(f"Wrote opencode config to {path}")
