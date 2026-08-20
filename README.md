# pyclaudius

A personal Telegram bot that relays messages to the [opencode](https://opencode.ai) CLI as a subprocess, giving full tool/MCP access. Inspired by [claude-telegram-relay](https://github.com/godagoo/claude-telegram-relay).

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [opencode](https://opencode.ai) installed (`opencode` in PATH)
- A [TensorX](https://docs.tensorx.ai/) API key
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

## Session commands

- `/help` — list all available commands
- `/clear` — end the current session and start fresh
- `/compact` — summarize the conversation to free up context window space (compaction is also automatic)
- `/context` — show token usage and cost of the last exchange

## MCP Tools

pyclaudius runs an in-process MCP server that gives the model direct tool access. A FastMCP HTTP server starts alongside the bot on `127.0.0.1`, and its address is written into the generated opencode config (see [Generated opencode config](#generated-opencode-config)) so opencode connects to it on every run. This lets the model call tools mid-conversation, see results, and reason over them.

Tools are registered conditionally based on feature flags (`MEMORY_ENABLED`, `CRON_ENABLED`, `EMAIL_ENABLED`, `BACKLOG_ENABLED`).

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
| `download_new_mail` | `EMAIL_ENABLED` | Download unseen emails as markdown |
| `delete_read_mail` | `EMAIL_ENABLED` | Delete all read emails from server |
| `list_backlog` | `BACKLOG_ENABLED` | List pending backlog items |
| `clear_backlog` | `BACKLOG_ENABLED` | Clear all pending backlog items |
| `replay_one` | `BACKLOG_ENABLED` | Pop a single backlog item and return its prompt |
| `replay_backlog` | `BACKLOG_ENABLED` | Pop all backlog items and return their prompts |

### Adding your own tools

You can extend the model with custom MCP tools by writing a plain Python function and registering it in `pyclaudius/mcp_tools/server.py`.

**1. Create a new module** in `pyclaudius/mcp_tools/` with your functions:

```python
# pyclaudius/mcp_tools/timezone_tool.py


def get_active_timezone(*, bot_data: dict) -> str:
    """Return the user's configured timezone."""
    tz = bot_data.get("user_timezone")
    return f"Active timezone: {tz or 'UTC (default)'}"
```

Your functions can accept `bot_data` — a shared dict typed as `BotData` (see `pyclaudius/bot_data.py` for all available keys, including `settings`, `memory`, `cron_jobs`, `backlog`, `user_timezone`, and `scheduler`). This gives your tool full access to bot state and configuration.

**2. Register it as an MCP tool** in `pyclaudius/mcp_tools/server.py` inside `create_mcp_server()`:

```python
from pyclaudius.mcp_tools import timezone_tool

@mcp.tool()
async def get_active_timezone() -> str:
    """Return the user's configured timezone."""
    return timezone_tool.get_active_timezone(bot_data=bot_data)
```

The `@mcp.tool()` decorator exposes the function to the model via MCP. The docstring becomes the tool description the model sees. The `bot_data` dict is captured via closure from the enclosing `create_mcp_server()` function.

You can also register tools conditionally based on feature flags:

```python
if settings.some_feature_enabled:
    @mcp.tool()
    async def my_tool() -> str:
        ...
```

That's it — with one caveat: add the function name to `_TOOLS_BY_FLAG` in the same module, so it lands in the generated config's `permission` map as `pyclaudius_<tool_name>` (opencode's namespacing). A test asserts the table matches the tools the server actually registers, so a forgotten entry fails the suite rather than silently denying the tool at runtime.

## Memory

pyclaudius supports persistent memory across sessions. When enabled, the model can remember and forget facts using MCP tools (`remember_fact`, `forget_memory`).

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

pyclaudius supports recurring and one-time scheduled tasks. When enabled, the model can create and manage jobs using MCP tools (`add_cron_job`, `schedule_once`, `remove_cron_job`, `list_cron_jobs`).

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

When a scheduled job fires, the model is instructed to respond with `[SILENT]` if there is nothing noteworthy to report. This suppresses the Telegram notification, avoiding spam from routine checks.

## Email Integration

pyclaudius can fetch emails from a dedicated IMAP account (e.g. a Gmail address that receives forwarded mail) and save them as markdown files in the opencode working directory. This lets the model read and reason over your emails.

> **Warning — pyclaudius can permanently delete emails from the server.** The `/deleteallreadmail` command (and the `delete_read_mail` MCP tool) issues an IMAP `EXPUNGE` with no undo. For this reason, **the recommended setup is a dedicated Gmail account** that only receives forwarded copies of emails you care about. That way you can grant pyclaudius full access without risking your primary inbox.

### Telegram commands

- `/downloadnewmail` — download unseen emails and save as markdown files
- `/deleteallreadmail` — delete all read emails from the server

### MCP tools

When enabled, two MCP tools are also registered so the model can fetch and clean mail autonomously:

| Tool | Description |
|------|-------------|
| `download_new_mail` | Download unseen emails and save as markdown |
| `delete_read_mail` | Delete all read (SEEN) emails from the server |

For forwarded emails, pyclaudius extracts and records the **original sender** rather than just the forwarder. It checks preserved headers (`X-Original-From`, `Resent-From`, `X-Original-Sender`) first, then falls back to scanning the body for Gmail / Outlook / Apple Mail forward boilerplate. The `**Original sender:**` field appears in the saved markdown when found.

### Configuration

```bash
EMAIL_ENABLED=true
EMAIL_IMAP_HOST=imap.gmail.com   # optional, default
EMAIL_IMAP_PORT=993              # optional, default
EMAIL_USER=your-llm-email@gmail.com
EMAIL_PASSWORD=your-app-password
```

For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833) (not your regular password). Emails are saved to `~/.pyclaudius-relay/work/emails/` as markdown files.

### Gmail setup

1. **Create a dedicated Gmail account** (e.g. `yourname-ai@gmail.com`). Never use your primary inbox — pyclaudius has delete access.

2. **Forward mail to it.** In your primary Gmail: Settings → See all settings → Forwarding and POP/IMAP → *Add a forwarding address*. Add the new address and confirm. You can also create a filter (Settings → Filters → Create new filter) to forward only specific senders or subjects instead of everything.

3. **Enable 2-Step Verification** on the dedicated account. This is required before App Passwords are available: Google Account → Security → 2-Step Verification → Turn on.

4. **Create an App Password**: Google Account → Security → App passwords → choose *Mail* (or *Other — custom name*) → Generate. Copy the 16-character password shown — you won't see it again.

5. **Enable IMAP** in the dedicated Gmail: Settings gear → See all settings → Forwarding and POP/IMAP → IMAP access: *Enable IMAP* → Save Changes.

6. **Set credentials** in `.env`:

```bash
EMAIL_USER=yourname-ai@gmail.com
EMAIL_PASSWORD=abcd efgh ijkl mnop   # the 16-char App Password (spaces optional)
```

## Timezone

Set your timezone so the model sees the correct local time and scheduled jobs fire at the right local time:

- `/timezone <city>` — set timezone with fuzzy matching (e.g. `/timezone Berlin`)
- Affects prompt time display and cron/schedule job scheduling
- Default is UTC if not set

The timezone is stored in `~/.pyclaudius-relay/timezone.json`.

## Model & Provider

pyclaudius drives opencode against [TensorX](https://docs.tensorx.ai/), which ships in
opencode's [models.dev](https://models.dev) registry — so no provider block is needed.
Setting the API key is enough to activate it:

```bash
TENSORX_API_KEY=sk-...                              # required
OPENCODE_MODEL=tensorx/moonshotai/kimi-k3           # optional, this is the default
```

Any model TensorX serves works — run `opencode models | grep tensorx` for the list.
Context limits, costs and capabilities come from the registry, so they do not need to be
configured.

The key is passed to the subprocess in its environment and is deliberately **not** written
into the generated config file. Everything else in the parent environment — including
`TELEGRAM_BOT_TOKEN` — is stripped from the subprocess.

Note there is no equivalent of the Claude CLI's `--effort`: `opencode run --variant`
accepts any string without validating it, and Kimi K3's reasoning is a plain on/off
toggle rather than an effort ladder, so pyclaudius does not expose it.

## Generated opencode config

On every start, pyclaudius writes `~/.pyclaudius-relay/opencode.json` (mode `0600`) and
points the subprocess at it with `OPENCODE_CONFIG`. It is regenerated each time because
it carries that run's MCP port. It contains:

- `model` — from `OPENCODE_MODEL`.
- `compaction` — automatic compaction with a 100k-token reserve, roughly "compact at 90%
  of the 1M window".
- `permission` — the tool allow/deny map (see [Allowed Tools](#allowed-tools)).
- `mcp` — the pyclaudius MCP server on this run's port.

Do not hand-edit it; your changes are overwritten on the next start. Use `.env` instead.

## Allowed Tools

opencode asks for confirmation before some tool calls, which would hang forever in a
relay with no terminal attached. pyclaudius therefore generates a `permission` map that
contains only `allow` and `deny` — never `ask`.

Allowed by default: `read`, `edit`, `bash`, `glob`, `grep`, `list`, `todowrite` (note
opencode has no separate `write` permission — writes fall under `edit`). Denied by
default: `webfetch`, `websearch`, `external_directory`, `doom_loop`, `task`, `skill`,
`question`. MCP tool names are added automatically.

To allow additional tools:

```bash
ALLOWED_TOOLS=["webfetch","websearch"]
```

As a blunt fallback there is `OPENCODE_AUTO_APPROVE=true`, which passes `--auto` and
approves anything not explicitly denied. It is off by default: it would also approve
tools that were never enumerated.

## Replay Backlog

When a run fails in a way that means the task was never executed, pyclaudius saves your
original message to a persistent backlog and notifies you. opencode reports provider
failures as structured events carrying an HTTP status, so the classification is exact:

- **401/403** — bad or missing `TENSORX_API_KEY`. No retry; it cannot self-heal.
- **429** — provider rate limit. No retry.
- **any other provider error** — retried once if the provider marked it retryable.
- **empty response** — always retried once, since this is the shape of an occasional
  opencode bug where stream events are dropped.

After the underlying issue clears, you can replay the saved messages.

This feature is **enabled by default**. To disable it:

```bash
BACKLOG_ENABLED=false
```

### Telegram commands

- `/listbacklog` — show pending backlog items
- `/clearbacklog` — clear all backlog items
- `/replaybacklog` — replay all backlog items sequentially
- `/replayone <number>` — replay a single backlog item by index

### How it works

1. You send a message
2. opencode returns a 401 from the provider
3. pyclaudius saves your original message to `~/.pyclaudius-relay/backlog.json`
4. You receive a notification with the pending count
5. Fix `TENSORX_API_KEY` in `.env` and restart
6. Use `/replaybacklog` to resend all saved messages

The backlog is also accessible via MCP tools (`list_backlog`, `clear_backlog`, `replay_one`, `replay_backlog`).

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

### 4. Install opencode

```bash
# As the pyclaudius user
curl -fsSL https://opencode.ai/install | bash
# Installs to ~/.opencode/bin — make sure that is on PATH, or set
# OPENCODE_PATH=/home/pyclaudius/.opencode/bin/opencode in .env

opencode --version
```

No `opencode auth login` step is needed: pyclaudius passes `TENSORX_API_KEY` from `.env`
into the subprocess environment.

Create opencode's state directories before running as a daemon — the systemd unit grants
write access to them, and under `ProtectHome=read-only` opencode cannot create them
itself:

```bash
mkdir -p ~/.local/share/opencode ~/.config/opencode ~/.cache/opencode ~/.pyclaudius-relay
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
