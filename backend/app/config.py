"""All settings come from environment variables / .env (never hard-coded secrets)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Looks for .env in the repo root (../.env) and in backend/ (.env); real env vars win.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://finora:finora_dev_password@localhost:5433/finora"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    limitforge_url: str = "http://localhost:8001"
    bureau_url: str = "http://localhost:8002"
    service_timeout_seconds: float = 5.0

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "noreply@finora.dev"
    frontend_url: str = "http://localhost:3000"

    cookie_name: str = "finora_token"
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:3000"
    seed_demo: bool = False

    # Login protection (feature 5)
    max_failed_logins: int = 5
    lockout_minutes: int = 15


settings = Settings()