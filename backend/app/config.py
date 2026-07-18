"""Central settings. Everything secret comes from env; nothing is hardcoded."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="JOBOPS_", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://jobops:jobops@postgres:5432/jobops"
    redis_url: str = "redis://redis:6379/0"

    # Optional local-LLM enrichment (workstation Ollama). Blank disables cleanly.
    ollama_base_url: str = ""
    ollama_model: str = "llama3.1"

    # Discovery cadence (minutes) per adapter class; per-source override in DB later.
    poll_interval_minutes: int = 30
    report_generation_hour_local: int = 4  # 04:00 America/Denver
    timezone: str = "America/Denver"

    # Safety rails
    high_volume_daily_submit_alert: int = 25
    policy_review_stale_days: int = 90

    # SMTP for the morning report email (operator sets password in .env on host)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    report_email_to: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
