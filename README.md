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

## Allowed Tools

By default, Claude CLI in print mode (`-p`) does not have permission to use tools like `WebSearch` or `WebFetch`. To pre-approve tools, set the `ALLOWED_TOOLS` environment variable:

```bash
ALLOWED_TOOLS=["WebSearch","WebFetch"]
```

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
