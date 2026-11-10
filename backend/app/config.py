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
    scheduler_enabled: bool = True
    # 카드번호 암호화 키(base64 32바이트). 아래 기본값은 개발 전용이며 .env의 CARD_ENCRYPTION_KEY로 덮어쓴다.
    card_encryption_key: str = "ZGV2LW9ubHktY2FyZC1rZXktMDEyMzQ1Njc4OWFiY2Q="


settings = Settings()
