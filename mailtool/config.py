"""Settings loaded from the local .env file. Secrets are never printed."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    imap_user: str = ""
    # repr=False keeps secrets out of tracebacks and debug output.
    imap_password: str = field(default="", repr=False)
    my_name: str = "سيف تركي"
    my_role: str = "العضو المنتدب لمجموعة الفنادق"
    anthropic_api_key: str | None = field(default=None, repr=False)
    gmail_client_id: str = ""
    gmail_client_secret: str = field(default="", repr=False)
    gmail_refresh_token: str = field(default="", repr=False)

    @property
    def has_gmail_api(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)

    @property
    def has_imap(self) -> bool:
        return bool(self.imap_user and self.imap_password)


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings from .env and the environment. Callers check what they need."""
    env_file = env_file or PROJECT_ROOT / ".env"
    if env_file.exists():
        _warn_if_world_readable(env_file)
        load_dotenv(env_file, override=False)
    return Settings(
        imap_user=os.getenv("IMAP_USER", "").strip(),
        imap_password=os.getenv("IMAP_APP_PASSWORD", "").replace(" ", ""),
        my_name=os.getenv("MY_NAME", Settings.my_name),
        my_role=os.getenv("MY_ROLE", Settings.my_role),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        gmail_client_id=os.getenv("GMAIL_CLIENT_ID", "").strip(),
        gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET", "").strip(),
        gmail_refresh_token=os.getenv("GMAIL_REFRESH_TOKEN", "").strip(),
    )


def _warn_if_world_readable(path: Path) -> None:
    if os.name == "posix" and path.stat().st_mode & 0o077:
        print(f"warning: {path.name} is readable by other users; run: chmod 600 {path.name}")
