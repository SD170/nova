"""All settings come from env vars (or apps/google-agent/.env). See .env.example."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

APP_ROOT = Path(__file__).resolve().parents[1]  # apps/google-agent/

# Least privilege: read mail, create drafts (never send), read the calendar, and manage
# ONLY the secondary calendar this app creates (it cannot edit or delete your own events).
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=APP_ROOT / ".env", extra="ignore")

    # mock = labeled demo data | google = real Gmail + Google Calendar
    workspace_backend: Literal["mock", "google"] = "mock"

    # Shared secret (same value as the Canvas service). If set, clients must send X-Canvas-Key.
    canvas_api_key: str = ""
    canvas_service_url: str = "http://localhost:9001"
    public_workspace_base: str = ""

    data_dir: Path = APP_ROOT / "data"
    timezone: str = "America/Phoenix"
    nova_calendar_name: str = "Nova"
    # Exam-prep PDFs are also saved here on the laptop running this service. The app on the
    # demo laptop downloads its own copy into its own ~/Nova/Exam Prep.
    nova_exam_dir: Path = Path("~/Nova/Exam Prep")
    auto_sync_minutes: float = 20

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: Annotated[list[str], NoDecode] = ["gemini-3.5-flash-lite"]
    gemini_timeout_seconds: float = 30

    tinyfish_api_key: str = ""

    # Supermemory (long-term memory). Key: console.supermemory.ai -> API keys. One namespace per student.
    supermemory_api_key: str = ""
    supermemory_namespace: str = "nova_student"
    supermemory_base_url: str = "https://api.supermemory.ai"

    # Amrita's news service (drafts/amrita-current-events), runs on this laptop
    news_service_url: str = "http://localhost:9004"
    news_api_key: str = ""   # only if her NEWS_AGENT_API_KEY is set (sent as X-Jarvis-Key)

    @field_validator("gemini_fallback_models", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("data_dir", "nova_exam_dir")
    @classmethod
    def _expand_home(cls, v: Path) -> Path:
        return Path(v).expanduser()

    @property
    def client_secret_path(self) -> Path:
        return self.data_dir / "client_secret.json"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "google_token.json"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def classify_cache_path(self) -> Path:
        return self.data_dir / "classify_cache.json"

    @property
    def gist_cache_path(self) -> Path:
        return self.data_dir / "gist_cache.json"

    @property
    def quizzes_dir(self) -> Path:
        return self.data_dir / "quizzes"

    @property
    def feed_path(self) -> Path:
        return self.data_dir / "feed.json"

    @property
    def exam_cache_path(self) -> Path:
        return self.data_dir / "exam_info.json"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def llm_active(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def gemini_models(self) -> list[str]:
        return [self.gemini_model, *self.gemini_fallback_models]


@lru_cache
def get_settings() -> Settings:
    return Settings()
