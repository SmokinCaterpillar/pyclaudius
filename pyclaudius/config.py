from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    telegram_bot_token: str
    telegram_user_id: str
    claude_path: str = "claude"
    relay_dir: Path = Path.home() / ".pyclaudius-relay"
    memory_enabled: bool = False
    max_memories: int = 100
    cron_enabled: bool = False
    allowed_tools: list[str] = []
    email_enabled: bool = False
    email_imap_host: str = "imap.gmail.com"
    email_imap_port: int = 993
    email_user: str = ""
    email_password: str = ""
    backlog_enabled: bool = True
    claude_timeout: int = 300
    tmux_session: str | None = None

    def __str__(self) -> str:
        fields = {
            k: "xxx" if k in ("telegram_bot_token", "email_password") else v
            for k, v in self.model_dump().items()
        }
        return f"Settings({', '.join(f'{k}={v!r}' for k, v in fields.items())})"

    @property
    def temp_dir(self) -> Path:
        return self.relay_dir / "temp"

    @property
    def uploads_dir(self) -> Path:
        return self.claude_work_dir / "uploads"

    @property
    def session_file(self) -> Path:
        return self.relay_dir / "session.json"

    @property
    def lock_file(self) -> Path:
        return self.relay_dir / "bot.lock"

    @property
    def memory_file(self) -> Path:
        return self.relay_dir / "memory.json"

    @property
    def cron_file(self) -> Path:
        return self.relay_dir / "cron.json"

    @property
    def timezone_file(self) -> Path:
        return self.relay_dir / "timezone.json"

    @property
    def backlog_file(self) -> Path:
        return self.relay_dir / "backlog.json"

    @property
    def claude_work_dir(self) -> Path:
        return self.relay_dir / "claude-work"

    @property
    def emails_dir(self) -> Path:
        return self.claude_work_dir / "emails"


def ensure_dirs(*, settings: Settings) -> None:
    """Create temp_dir, uploads_dir, claude_work_dir, and emails_dir if they don't exist."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.claude_work_dir.mkdir(parents=True, exist_ok=True)
    if settings.email_enabled:
        settings.emails_dir.mkdir(parents=True, exist_ok=True)
