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
    gemini_api_version: str = "v1beta"   # 시스템 지시문(system instruction)은 v1beta에서 지원된다
    # RAG(문서 검색). 임베딩 차원은 db/003_rag.sql의 vector(768)과 맞아야 한다.
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    rag_top_k: int = 4
    rag_min_score: float = 0.65   # 코사인 유사도 기준. 이보다 낮으면 '근거 없음'(무관 질문 최대 0.62, 정답 최소 0.71 사이). scripts/eval_rag.py로 조정
    agent_polish_reply: bool = True   # 답변 문장을 모델이 다듬게 할지(숫자 검증을 통과해야만 사용)
    # 카드번호 암호화 키(base64 32바이트). 아래 기본값은 개발 전용이며 .env의 CARD_ENCRYPTION_KEY로 덮어쓴다.
    card_encryption_key: str = "ZGV2LW9ubHktY2FyZC1rZXktMDEyMzQ1Njc4OWFiY2Q="

    @field_validator("gemini_model", mode="before")
    @classmethod
    def _model_default(cls, v):
        return v or "gemini-2.5-flash"  # .env에 값 없이 `GEMINI_MODEL=`만 있어도 기본값을 쓴다


settings = Settings()
