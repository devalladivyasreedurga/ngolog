from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Postgres in production (Render); SQLite works for local dev and tests.
    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'ngolog.db'}"
    secret_key: str = "dev-only-change-me"
    public_app_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    # Demo auth: passwordless sign-in by email. Reviewer role only for allowlisted emails.
    demo_auth_enabled: bool = True
    reviewer_emails: str = ""

    # PayPal (sandbox only for the hackathon)
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

    # AI. Empty key = manual mode: NGOs enter claims and receipt totals by hand.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"

    # Elastic (optional). Without it, retrieval falls back to Postgres keyword search.
    elastic_url: str = ""
    elastic_api_key: str = ""
    elastic_inference_id: str = ""  # e.g. an ELSER endpoint id; enables semantic_text search

    # Evidence storage
    upload_dir: Path = REPO_ROOT / "backend" / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    # Agent policy
    max_clarification_rounds: int = 3
    reminder_interval_days: int = 1
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 300

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def reviewer_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.reviewer_emails.split(",") if e.strip()}

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
