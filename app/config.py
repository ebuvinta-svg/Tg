from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admins: List[int]
    log_level: str


def _read_env_variable(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def load_settings() -> Settings:
    # Lazy import to avoid hard dependency if user doesn't use .env
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(override=False)
    except Exception:
        pass

    token = _read_env_variable("BOT_TOKEN")
    admins_csv = os.getenv("ADMINS", "").strip()
    admins = [int(x) for x in admins_csv.split(",") if x.strip().isdigit()]
    log_level = os.getenv("BOT_LOG_LEVEL", "INFO").upper()
    return Settings(bot_token=token, admins=admins, log_level=log_level)
