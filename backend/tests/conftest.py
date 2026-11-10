"""테스트 공통. 실제 PostgreSQL(docker compose의 db)에 연결하고, 메일은 전송 대신 가로채 인증번호를 꺼낸다."""
import random
import re
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.common import mailer
from app.config import settings
from app.main import app

PASSWORD = "Test!2345"
PIN = "135790"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    with psycopg.connect(settings.database_url) as conn:
        ids = "SELECT id FROM users WHERE login_id LIKE 't\\_%'"
        for table in ("term_agreements", "login_histories", "notifications"):
            conn.execute(f"DELETE FROM {table} WHERE user_id IN ({ids})")
        conn.execute("DELETE FROM users WHERE login_id LIKE 't\\_%'")
        conn.execute("DELETE FROM verification_codes WHERE email LIKE '%@test.example'")


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


@pytest.fixture()
def client(outbox):
    with TestClient(app) as c:
        yield c


def last_code(outbox, email: str) -> str:
    bodies = [b for to, _, b in outbox if to == email.lower()]
    return re.search(r"\d{6}", bodies[-1]).group()


def new_identity() -> dict:
    tag = uuid.uuid4().hex[:10]
    return {"login_id": f"t_{tag}", "email": f"{tag}@test.example",
            "phone_num": f"010-{random.randint(9000, 9999)}-{random.randint(1000, 9999)}", "user_name": "테스트"}


def required_term_ids(client) -> list[int]:
    return [t["id"] for t in client.get("/api/terms?category=SIGNUP").json() if t["required"]]


def signup_user(client, outbox, **overrides) -> dict:
    """이메일 인증까지 마치고 가입한 뒤 로그인 정보를 돌려준다."""
    ident = new_identity()
    assert client.post("/api/auth/email-codes", json={"email": ident["email"], "purpose": "SIGNUP"}).status_code == 200
    code = last_code(outbox, ident["email"])
    assert client.post("/api/auth/email-codes/verify",
                       json={"email": ident["email"], "purpose": "SIGNUP", "code": code}).status_code == 200
    body = {**ident, "password": PASSWORD, "pin": PIN, "agreed_term_ids": required_term_ids(client), **overrides}
    res = client.post("/api/auth/signup", json=body)
    assert res.status_code == 201, res.text
    return {**ident, "password": PASSWORD, "pin": PIN, "id": res.json()["id"]}
