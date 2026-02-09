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

## Memory

pyclaudius supports persistent memory across sessions. When enabled, Claude can remember and forget facts automatically by including tags in its responses (tags are stripped before the message is sent to you):

- `[REMEMBER: user likes coffee]` — stores a fact
- `[FORGET: coffee]` — removes matching facts

You can also manage memory manually with Telegram commands:

- `/remember` — list all stored facts
- `/forget <keyword>` — remove facts matching a keyword

Enable it via environment variables:

```bash
MEMORY_ENABLED=true
MAX_MEMORIES=100   # optional, default 100
```

Memories are stored in `~/.pyclaudius-relay/memory.json` and injected into every prompt. To clear memory, delete the file or edit it manually.

## Scheduled Tasks (Cron)

pyclaudius supports recurring and one-time scheduled tasks. When enabled, Claude can create and manage jobs by including tags in its responses:

- `[CRON_ADD: */30 * * * * | check the weather]` — recurring job (standard 5-field cron)
- `[SCHEDULE: 2026-03-01 09:00 | remind me about the meeting]` — one-time job
- `[CRON_REMOVE: 1]` — remove a job by number
- `[CRON_LIST]` — list all scheduled jobs

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

When a scheduled job fires, Claude is instructed to respond with `[SILENT]` if there is nothing noteworthy to report. This suppresses the Telegram notification, avoiding spam from routine checks. Memory and cron tags in a silent response are still processed normally.

## Allowed Tools

By default, Claude CLI in print mode (`-p`) does not have permission to use tools like `WebSearch` or `WebFetch`. To pre-approve tools, set the `ALLOWED_TOOLS` environment variable:

```bash
ALLOWED_TOOLS=["WebSearch","WebFetch"]
```

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
