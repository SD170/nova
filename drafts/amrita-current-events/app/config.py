"""Env settings. Secrets live in .env (gitignored); shared non-secret values in repo-root shared.env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")
_load_env(ROOT.parent.parent / "shared.env")


@dataclass(frozen=True)
class Settings:
    # Shared secret for the brain-facing tool endpoints (header X-Jarvis-Key), same scheme as browser-agent.
    api_key: str = os.environ.get("NEWS_AGENT_API_KEY", "")
    port: int = int(os.environ.get("NEWS_PORT", "9004"))
    cache_ttl_minutes: int = int(os.environ.get("NEWS_CACHE_TTL_MINUTES", "15"))
    default_since_hours: int = int(os.environ.get("NEWS_SINCE_HOURS", "24"))
    per_topic_max: int = int(os.environ.get("NEWS_PER_TOPIC_MAX", "15"))
    # Browser origins allowed to call the tools: team UI dev server + Electron ("null" = file://).
    cors_origins: tuple = tuple(o.strip() for o in os.environ.get(
        "NEWS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,null").split(",") if o.strip())
    push_enabled: bool = os.environ.get("PUSH_ENABLED", "1") != "0"


settings = Settings()
