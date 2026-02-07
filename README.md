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

Create a `.env` file in the project root:

```bash
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_USER_ID=your-telegram-user-id
```

Optional:

```bash
CLAUDE_PATH=/usr/local/bin/claude   # default: claude
RELAY_DIR=/opt/pyclaudius/data      # default: ~/.pyclaudius-realy
```

### Run locally

```bash
uv run pyclaudius
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
cat > ~/pyclaudius/.env <<EOF
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_USER_ID=your-telegram-user-id
EOF
chmod 600 ~/pyclaudius/.env
```

### 6. Set up systemd service

Switch back to root and create the unit file:

```bash
sudo tee /etc/systemd/system/pyclaudius.service <<EOF
[Unit]
Description=pyclaudius Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pyclaudius
Group=pyclaudius
WorkingDirectory=/home/pyclaudius/pyclaudius
ExecStart=/home/pyclaudius/.local/bin/uv run pyclaudius
Restart=on-failure
RestartSec=10

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/pyclaudius/.pyclaudius-realy
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pyclaudius
sudo systemctl start pyclaudius
```

### 7. Manage the service

```bash
# Check status
sudo systemctl status pyclaudius

# View logs
sudo journalctl -u pyclaudius -f

# Restart after code changes
cd /home/pyclaudius/pyclaudius && sudo -u pyclaudius git pull
sudo systemctl restart pyclaudius

# Stop
sudo systemctl stop pyclaudius
```

### Updating

```bash
sudo -u pyclaudius bash -c "cd ~/pyclaudius && git pull && uv sync"
sudo systemctl restart pyclaudius
```

## Development

```bash
uv run pytest -v          # run tests
uv run ruff check .       # lint
uv run mypy pyclaudius/   # type check
```

## License

MIT
