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
    allowed_tools: list[str] = []

    def __str__(self) -> str:
        fields = {
            k: "xxx" if k == "telegram_bot_token" else v
            for k, v in self.model_dump().items()
        }
        return f"Settings({', '.join(f'{k}={v!r}' for k, v in fields.items())})"

    @property
    def temp_dir(self) -> Path:
        return self.relay_dir / "temp"

    @property
    def uploads_dir(self) -> Path:
        return self.relay_dir / "uploads"

    @property
    def session_file(self) -> Path:
        return self.relay_dir / "session.json"

    @property
    def lock_file(self) -> Path:
        return self.relay_dir / "bot.lock"

    @property
    def memory_file(self) -> Path:
        return self.relay_dir / "memory.json"


def ensure_dirs(*, settings: Settings) -> None:
    """Create temp_dir and uploads_dir if they don't exist."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
