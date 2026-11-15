"""All settings come from env vars (or apps/browser-agent/.env). See .env.example."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

APP_ROOT = Path(__file__).resolve().parents[1]  # apps/browser-agent/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=APP_ROOT / ".env", extra="ignore")

    # mock = labeled demo data, no keys needed | tinyfish = real Canvas via TinyFish
    browser_backend: Literal["mock", "tinyfish"] = "mock"

    # Shared secret: if set, clients must send header X-Canvas-Key (needed once public)
    canvas_api_key: str = ""

    cache_ttl_minutes: int = 30
    data_dir: Path = APP_ROOT / "data"
    canvas_base_url: str = "https://canvas.asu.edu"
    sync_days: int = 14        # fetch items due up to N days ahead
    sync_past_days: int = 0    # ...and N days back (e.g. to catch missing work)
    # Optional: only these Canvas course ids (comma-separated). Empty = auto.
    canvas_course_ids: Annotated[list[str], NoDecode] = []

    # Course materials (see app/materials.py)
    materials_max_mb: float = 25           # skip bigger files (whole textbooks)
    materials_prefetch_days: int = 7       # pre-extract modules dated today..+N days (+ syllabus)
    materials_prefetch_limit: int = 12     # max files pre-extracted per course per sync
    materials_prefetch_seconds: float = 60 # time budget for pre-extraction per sync

    # Classification LLM (Gemini). Used only if enabled AND a key is set.
    classifier_llm_enabled: bool = True
    llm_confidence_threshold: float = 0.7
    gemini_api_key: str = ""
    # Primary model, then fallbacks tried in order if it is slow/busy (checked 2026-11-14:
    # 3.5-flash ~5 s, 3.5-flash-lite ~1 s; 3.7/3.8-flash were hanging).
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: Annotated[list[str], NoDecode] = ["gemini-3.5-flash-lite"]
    gemini_timeout_seconds: float = 30

    # TinyFish: API key + the Browser Context Profile that is signed into Canvas
    tinyfish_api_key: str = ""
    tinyfish_base_url: str = "https://agent.tinyfish.ai"
    tinyfish_profile_id: str = ""

    @field_validator("canvas_course_ids", "gemini_fallback_models", mode="before")
    @classmethod
    def _split_ids(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("data_dir")
    @classmethod
    def _expand_home(cls, v: Path) -> Path:
        return Path(v).expanduser()

    @property
    def snapshot_path(self) -> Path:
        return self.data_dir / "canvas_snapshot.json"

    @property
    def materials_dir(self) -> Path:
        return self.data_dir / "materials"

    @property
    def llm_active(self) -> bool:
        return self.classifier_llm_enabled and bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
