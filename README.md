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

pyclaudius supports persistent memory across sessions. When enabled, Claude can remember facts by including `[REMEMBER: ...]` tags in its responses (these tags are stripped before the message is sent to you).

Enable it via environment variables:

```bash
MEMORY_ENABLED=true
MAX_MEMORIES=100   # optional, default 100
```

Memories are stored in `~/.pyclaudius-relay/memory.json` and injected into every prompt. To clear memory, delete the file or edit it manually.

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

Edit `daemon/pyclaudius.service` and replace `YOUR_USERNAME` with `pyclaudius`, then:

```bash
sudo cp ~/pyclaudius/daemon/pyclaudius.service /etc/systemd/system/
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
