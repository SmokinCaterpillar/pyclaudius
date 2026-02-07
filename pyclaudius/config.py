from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    telegram_bot_token: str
    telegram_user_id: str
    claude_path: str = "claude"
    relay_dir: Path = Path.home() / ".pyclaudius-realy"

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


def ensure_dirs(*, settings: Settings) -> None:
    """Create temp_dir and uploads_dir if they don't exist."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
