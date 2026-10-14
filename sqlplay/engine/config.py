"""Load settings from .env (current folder, project folder, then ~/.sqlplay/.env)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_loaded = False


def load() -> None:
    global _loaded
    if _loaded:
        return
    for p in (Path.cwd() / ".env", PROJECT_ROOT / ".env", Path.home() / ".sqlplay" / ".env"):
        if p.exists():
            load_dotenv(p, override=False)
    _loaded = True


def get(name: str, default: str = "") -> str:
    load()
    return os.environ.get(name, default) or default
