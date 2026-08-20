from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REDACTED_FIELDS = ("telegram_bot_token", "email_password", "tensorx_api_key")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    telegram_bot_token: str
    telegram_user_id: str
    opencode_path: str = "opencode"
    tensorx_api_key: str = ""
    opencode_model: str = "tensorx/moonshotai/kimi-k3"
    opencode_timeout: int = 300
    opencode_context_limit: int = 1_048_576
    opencode_auto_approve: bool = False
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

    def __str__(self) -> str:
        fields = {
            k: "xxx" if k in _REDACTED_FIELDS else v
            for k, v in self.model_dump().items()
        }
        return f"Settings({', '.join(f'{k}={v!r}' for k, v in fields.items())})"

    @property
    def temp_dir(self) -> Path:
        return self.relay_dir / "temp"

    @property
    def uploads_dir(self) -> Path:
        return self.opencode_work_dir / "uploads"

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
    def opencode_work_dir(self) -> Path:
        return self.relay_dir / "work"

    @property
    def opencode_config_file(self) -> Path:
        return self.relay_dir / "opencode.json"

    @property
    def emails_dir(self) -> Path:
        return self.opencode_work_dir / "emails"

    @property
    def provider_id(self) -> str:
        """Provider half of ``opencode_model`` (e.g. ``tensorx``).

        The opencode server's summarize endpoint wants provider and model as
        separate fields, and ``opencode_model`` is a ``provider/model`` string
        where the model half may itself contain slashes.
        """
        return self.opencode_model.split("/", 1)[0]

    @property
    def model_id(self) -> str:
        """Model half of ``opencode_model`` (e.g. ``moonshotai/kimi-k3``)."""
        _, _, model = self.opencode_model.partition("/")
        return model


def ensure_dirs(*, settings: Settings) -> None:
    """Create temp_dir, uploads_dir, opencode_work_dir, and emails_dir if they don't exist."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.opencode_work_dir.mkdir(parents=True, exist_ok=True)
    if settings.email_enabled:
        settings.emails_dir.mkdir(parents=True, exist_ok=True)
