from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SmartMonitor"
    environment: str = "production"

    database_url: str = "postgresql+psycopg2://smartmonitor:smartmonitor@postgres:5432/smartmonitor"
    redis_url: str = "redis://redis:6379/0"
    celery_eager: bool = False

    jwt_secret: str = "change-me-please"
    jwt_ttl_minutes: int = 720
    admin_username: str = "admin"
    admin_password: str = "admin123"

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-5.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout: float = 40.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    report_hour_utc: int = 9

    incident_threshold: int = 2
    dispatch_interval_seconds: int = 10
    system_tests_interval_minutes: int = 60
    action_webhook_url: str = ""

    backend_internal_url: str = "http://backend:8000"
    qa_live_llm: bool = True

    log_dir: str = "logs"
    log_level: str = "INFO"
    seed_demo: bool = True
    cors_origins: str = "*"
    frontend_dir: str = ""

    @property
    def openrouter_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.strip() and self.telegram_chat_id.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
