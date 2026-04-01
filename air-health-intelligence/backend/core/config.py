"""
core/config.py
Centralised settings loaded from environment variables via pydantic-settings.
"""
from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────
    app_name: str = "AI Urban Air & Health Risk Intelligence System"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    secret_key: str = "change-me-in-production"
    api_key_header: str = "X-API-Key"
    internal_api_key: str = "internal-key"

    # ── MongoDB ────────────────────────────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "air_health_intelligence"

    # ── AI / LLM ──────────────────────────────────────────────────
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "claude-opus-4-5"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.3

    # ── External Data APIs ─────────────────────────────────────────
    openweathermap_api_key: str = ""
    openaq_api_key: str = ""

    # ── Alert Thresholds ──────────────────────────────────────────
    default_aqi_warning_threshold: float = 100.0
    default_aqi_danger_threshold: float = 150.0
    default_pm25_warning_threshold: float = 35.4
    default_pm25_danger_threshold: float = 55.4

    # ── Ingestion Scheduler ───────────────────────────────────────
    ingestion_interval_seconds: int = 300
    monitored_cities: str = "Delhi,Mumbai,Bangalore,Chennai,Kolkata,Hyderabad"

    # ── CORS ──────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # ── Rate Limiting ─────────────────────────────────────────────
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ── Computed properties ───────────────────────────────────────
    @property
    def monitored_cities_list(self) -> List[str]:
        return [c.strip() for c in self.monitored_cities.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


settings = get_settings()
