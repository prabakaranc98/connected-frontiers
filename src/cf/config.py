"""Settings from .env and configs/*.yaml. Secrets are read from the environment only, never logged."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
DATA = ROOT / "data"
EVAL = ROOT / "eval"

load_dotenv(ROOT / ".env", override=False)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value if value not in ("", None) else default


def is_set(name: str) -> bool:
    """True if a secret is present. Never returns or prints its value."""
    return bool(os.getenv(name))


def load_yaml(name: str) -> dict:
    path = CONFIGS / name
    with path.open() as f:
        return yaml.safe_load(f) or {}
