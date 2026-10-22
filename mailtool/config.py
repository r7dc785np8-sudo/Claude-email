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
    imap_user: str
    # repr=False keeps the password out of tracebacks and debug output.
    imap_password: str = field(repr=False)
    my_name: str = "سيف تركي"
    my_role: str = "العضو المنتدب لمجموعة الفنادق"
    anthropic_api_key: str | None = field(default=None, repr=False)


def load_settings(env_file: Path | None = None) -> Settings:
    env_file = env_file or PROJECT_ROOT / ".env"
    if env_file.exists():
        _warn_if_world_readable(env_file)
        load_dotenv(env_file, override=False)

    user = os.getenv("IMAP_USER", "").strip()
    password = os.getenv("IMAP_APP_PASSWORD", "").replace(" ", "")
    if not user or not password:
        raise ConfigError(
            f"IMAP_USER and IMAP_APP_PASSWORD must be set in {env_file} "
            "(copy .env.example to .env and fill it in)."
        )
    return Settings(
        imap_user=user,
        imap_password=password,
        my_name=os.getenv("MY_NAME", Settings.my_name),
        my_role=os.getenv("MY_ROLE", Settings.my_role),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
    )


def _warn_if_world_readable(path: Path) -> None:
    if os.name == "posix" and path.stat().st_mode & 0o077:
        print(f"warning: {path.name} is readable by other users; run: chmod 600 {path.name}")
