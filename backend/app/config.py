from pathlib import Path

from pydantic import field_validator
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
    # Gemini (에이전트). 키는 .env의 GEMINI_API_KEY로만 넣는다. 모델명은 구현 시점의 공식 문서로 확인해 바꾼다.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout: int = 30
    agent_polish_reply: bool = True   # 답변 문장을 모델이 다듬게 할지(숫자 검증을 통과해야만 사용)
    # 카드번호 암호화 키(base64 32바이트). 아래 기본값은 개발 전용이며 .env의 CARD_ENCRYPTION_KEY로 덮어쓴다.
    card_encryption_key: str = "ZGV2LW9ubHktY2FyZC1rZXktMDEyMzQ1Njc4OWFiY2Q="

    @field_validator("gemini_model", mode="before")
    @classmethod
    def _model_default(cls, v):
        return v or "gemini-2.5-flash"  # .env에 값 없이 `GEMINI_MODEL=`만 있어도 기본값을 쓴다


settings = Settings()
