# pyclaudius

A personal Telegram bot that relays messages to the Claude CLI as a subprocess, giving full tool/MCP access. Inspired by [claude-telegram-relay](https://github.com/godagoo/claude-telegram-relay).

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) installed and authenticated (`claude` in PATH)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram user ID from [@userinfobot](https://t.me/userinfobot)

### Install

```bash
git clone <repo-url> && cd pyclaudius
uv sync --all-extras
```

### Configure

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

See [`.env.example`](.env.example) for all available options.

### Run locally

```bash
uv run pyclaudius
```

## MCP Tools

pyclaudius runs an in-process MCP server that gives Claude direct tool access. A FastMCP HTTP server starts alongside the bot on `127.0.0.1` and Claude CLI connects to it via `--mcp-config`. This lets Claude call tools mid-conversation, see results, and reason over them.

Tools are registered conditionally based on feature flags (`MEMORY_ENABLED`, `CRON_ENABLED`).

### Available tools

| Tool | Feature flag | Description |
|------|-------------|-------------|
| `remember_fact` | `MEMORY_ENABLED` | Remember an important fact about the user |
| `forget_memory` | `MEMORY_ENABLED` | Forget memories matching a keyword or by index |
| `list_memories` | `MEMORY_ENABLED` | List all stored memory facts |
| `add_cron_job` | `CRON_ENABLED` | Add a recurring cron job (5-field cron expression) |
| `schedule_once` | `CRON_ENABLED` | Schedule a one-time task at a specific datetime |
| `remove_cron_job` | `CRON_ENABLED` | Remove a scheduled job by index |
| `list_cron_jobs` | `CRON_ENABLED` | List all scheduled cron jobs |

### Adding your own tools

You can extend Claude with custom MCP tools by writing a plain Python function and registering it in `pyclaudius/mcp_tools/server.py`.

**1. Write your function** in a module (e.g. `pyclaudius/operations.py` or a new file):

```python
# pyclaudius/operations.py

def get_bot_uptime(*, bot_data: dict) -> str:
    """Return how long the bot has been running."""
    import datetime
    started: datetime.datetime = bot_data["started_at"]
    delta = datetime.datetime.now(tz=datetime.UTC) - started
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"Uptime: {hours}h {minutes}m {seconds}s"
```

Every function receives `bot_data` — a shared dict that holds `settings`, `memory`, `cron_jobs`, `scheduler`, and anything else you store on `app.bot_data` in `main.py`. This gives your tool full access to bot state and configuration.

**2. Register it as an MCP tool** in `pyclaudius/mcp_tools/server.py` inside `create_mcp_server()`:

```python
@mcp.tool()
async def get_bot_uptime() -> str:
    """Return how long the bot has been running."""
    return operations.get_bot_uptime(bot_data=bot_data)
```

The `@mcp.tool()` decorator exposes the function to Claude via MCP. The docstring becomes the tool description that Claude sees. The `bot_data` dict is captured via closure from the enclosing `create_mcp_server()` function.

You can also register tools conditionally based on feature flags:

```python
if settings.some_feature_enabled:
    @mcp.tool()
    async def my_tool() -> str:
        ...
```

That's it. The tool is automatically discovered by Claude CLI, added to `--allowedTools` via the `mcp__pyclaudius__*` wildcard, and available in every conversation.

## Memory

pyclaudius supports persistent memory across sessions. When enabled, Claude can remember and forget facts using MCP tools (`remember_fact`, `forget_memory`).

You can also manage memory manually with Telegram commands:

- `/remember <fact>` — store a fact
- `/forget <keyword or number>` — remove facts matching a keyword or by index
- `/listmemory` — list all stored facts

Enable it via environment variables:

```bash
MEMORY_ENABLED=true
MAX_MEMORIES=100   # optional, default 100
```

Memories are stored in `~/.pyclaudius-relay/memory.json` and injected into every prompt. To clear memory, delete the file or edit it manually.

## Scheduled Tasks (Cron)

pyclaudius supports recurring and one-time scheduled tasks. When enabled, Claude can create and manage jobs using MCP tools (`add_cron_job`, `schedule_once`, `remove_cron_job`, `list_cron_jobs`).

You can also manage jobs with Telegram commands:

- `/addcron <min> <hour> <day> <month> <weekday> <prompt>` — add a recurring job
- `/schedule <YYYY-MM-DD HH:MM> | <prompt>` — schedule a one-time task
- `/listcron` — list all scheduled jobs
- `/removecron <number>` — remove a job by number
- `/testcron <number>` — immediately test a job without waiting for its schedule

Enable it via environment variables:

```bash
CRON_ENABLED=true
```

Jobs are stored in `~/.pyclaudius-relay/cron.json` and survive restarts.

### Silent responses

When a scheduled job fires, Claude is instructed to respond with `[SILENT]` if there is nothing noteworthy to report. This suppresses the Telegram notification, avoiding spam from routine checks.

## Timezone

Set your timezone so Claude sees the correct local time and scheduled jobs fire at the right local time:

- `/timezone <city>` — set timezone with fuzzy matching (e.g. `/timezone Berlin`)
- Affects prompt time display and cron/schedule job scheduling
- Default is UTC if not set

The timezone is stored in `~/.pyclaudius-relay/timezone.json`.

## Allowed Tools

By default, Claude CLI in print mode (`-p`) does not have permission to use tools like `WebSearch` or `WebFetch`. To pre-approve tools, set the `ALLOWED_TOOLS` environment variable:

```bash
ALLOWED_TOOLS=["WebSearch","WebFetch"]
```

MCP tool names are automatically added to the allowed tools list.

## Auto-refresh authentication

When Claude CLI is used in print mode (`-p`), it does not automatically refresh expired OAuth tokens. pyclaudius can detect authentication errors and spawn a brief interactive Claude session to trigger a token refresh.

**This feature is disabled by default** because it is a gray area in the Claude CLI terms of service — the `-p` flag intentionally skips interactive authentication flows, and this workaround bypasses that by spawning a short-lived interactive session that immediately exits after the token is refreshed.

To enable it:

```bash
AUTO_REFRESH_AUTH=true
```

When enabled, if an API call returns an authentication error (expired token, 401), pyclaudius will:
1. Spawn `claude` interactively and pipe `/exit` to trigger the OAuth refresh
2. Retry the original request with the refreshed token

If you are uncomfortable with this approach, leave the setting disabled and manually re-authenticate with `claude auth login` when tokens expire.

## Deploying on a server (Hetzner, etc.)

### 1. Provision the server

Any VPS with Ubuntu 22.04+ works. A Hetzner CX22 (2 vCPU, 4 GB RAM) is more than enough.

```bash
ssh root@your-server-ip
apt update && apt upgrade -y
```

### 2. Create a dedicated user

```bash
adduser --disabled-password pyclaudius
su - pyclaudius
```

### 3. Install uv and the project

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

git clone <repo-url> ~/pyclaudius && cd ~/pyclaudius
uv sync
```

### 4. Install and authenticate the Claude CLI

```bash
# Install Claude CLI (as the pyclaudius user)
npm install -g @anthropic-ai/claude-code
# Or download the standalone binary

# Authenticate
claude auth login
```

### 5. Create the .env file

```bash
cp ~/pyclaudius/.env.example ~/pyclaudius/.env
# Edit with your values
nano ~/pyclaudius/.env
chmod 600 ~/pyclaudius/.env
```

### 6. Set up as a daemon

Ready-to-use service files are in the [`daemon/`](daemon/) directory.

**Linux (systemd):**

Install the service (automatically replaces `YOUR_USERNAME` with your login name):

```bash
sed "s/YOUR_USERNAME/$USER/g" ~/pyclaudius/daemon/pyclaudius.service | sudo tee /etc/systemd/system/pyclaudius.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable pyclaudius
sudo systemctl start pyclaudius
```

See the comments in [`daemon/pyclaudius.service`](daemon/pyclaudius.service) for full instructions.

**macOS (launchd):**

See [`daemon/launchagent.plist`](daemon/launchagent.plist).

**Windows:**

See [`daemon/README-WINDOWS.md`](daemon/README-WINDOWS.md).

### 7. Manage the service

```bash
# Check status
sudo systemctl status pyclaudius

# View logs
sudo journalctl -u pyclaudius -f

# Restart after code changes
sudo -u pyclaudius bash -c "cd ~/pyclaudius && git pull && uv sync"
sudo systemctl restart pyclaudius

# Stop
sudo systemctl stop pyclaudius
```

## Development

```bash
uv run pytest -v          # run tests
uv run ruff check .       # lint
uv run mypy pyclaudius/   # type check
```

## License

MIT
