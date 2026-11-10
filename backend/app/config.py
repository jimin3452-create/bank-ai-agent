from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://bank:bank@localhost:5433/bank"
    jwt_secret: str = "dev-only-change-me"
    jwt_minutes: int = 30
    app_env: str = "dev"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    cookie_secure: bool = False


settings = Settings()
