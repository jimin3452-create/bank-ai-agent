"""스크립트 공통: .env 로드와 DB 연결."""
import base64
import os
import re
import secrets
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """.env를 읽어 환경변수에 넣는다. 없으면 .env.example을 복사하고 비밀값을 새로 만든다."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        text = re.sub(r"^JWT_SECRET=\s*$", f"JWT_SECRET={secrets.token_urlsafe(48)}", text, flags=re.M)
        key = base64.b64encode(secrets.token_bytes(32)).decode()
        text = re.sub(r"^CARD_ENCRYPTION_KEY=\s*$", f"CARD_ENCRYPTION_KEY={key}", text, flags=re.M)
        env_path.write_text(text, encoding="utf-8")
        print("[env] .env가 없어서 .env.example로 새로 만들었습니다. GEMINI_API_KEY는 직접 채우세요.")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])
