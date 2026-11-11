"""테스트 공통. 실제 PostgreSQL(docker compose의 db)에 연결하고, 메일은 전송 대신 가로채 인증번호를 꺼낸다."""
import os
import random
import re
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

os.environ["SCHEDULER_ENABLED"] = "false"  # 테스트에서는 스케줄러를 켜지 않는다(필요하면 직접 호출)

from app.common import mailer
from app.config import settings
from app.main import app

PASSWORD = "Test!2345"
PIN = "135790"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    with psycopg.connect(settings.database_url) as conn:
        users = "SELECT id FROM users WHERE login_id LIKE 't\\_%'"
        accounts = f"SELECT id FROM accounts WHERE user_id IN ({users})"
        cards = f"SELECT id FROM cards WHERE account_id IN ({accounts})"
        for sql in (
            # 에이전트 대화 기록과 체크포인트(스레드 ID는 '회원ID:세션ID')
            f"DELETE FROM agent_messages WHERE user_id IN ({users})",
            *[f"DELETE FROM {tbl} WHERE EXISTS (SELECT 1 FROM users u WHERE u.login_id LIKE 't\_%' AND {tbl}.thread_id LIKE u.id::text || ':%')"
              for tbl in ("checkpoint_writes", "checkpoint_blobs", "checkpoints")],
            f"DELETE FROM statement_requests WHERE account_id IN ({accounts})",
            f"DELETE FROM account_transactions WHERE account_id IN ({accounts})",
            f"DELETE FROM card_payments WHERE card_id IN ({cards})",
            f"DELETE FROM transfers WHERE from_account_id IN ({accounts}) OR to_account_id IN ({accounts})",
            f"DELETE FROM auto_transfers WHERE from_account_id IN ({accounts}) OR to_account_id IN ({accounts})",
            f"DELETE FROM cards WHERE account_id IN ({accounts})",
            f"DELETE FROM accounts WHERE user_id IN ({users})",
            f"DELETE FROM budgets WHERE user_id IN ({users})",
            f"DELETE FROM favorite_recipients WHERE user_id IN ({users})",
            f"DELETE FROM merchant_category_map WHERE user_id IN ({users})",
            f"DELETE FROM term_agreements WHERE user_id IN ({users})",
            f"DELETE FROM login_histories WHERE user_id IN ({users})",
            f"DELETE FROM notifications WHERE user_id IN ({users})",
            "DELETE FROM users WHERE login_id LIKE 't\\_%'",
            "DELETE FROM verification_codes WHERE email LIKE '%@test.example'",
        ):
            conn.execute(sql)


@pytest.fixture(autouse=True)
def _hermetic_embedding():
    """테스트는 실제 Gemini 임베딩을 부르지 않는다(빠르고 결정적이게). 해시 임베딩은 실제 지식베이스 벡터와 거의 무관해 기준 점수를 넘지 않는다."""
    from app.agent.rag.embeddings import HashEmbedder, set_embedder
    set_embedder(HashEmbedder())
    yield
    set_embedder(None)


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


@pytest.fixture()
def files(monkeypatch):
    """첨부 메일(거래내역 CSV)을 가로챈다."""
    sent = []
    monkeypatch.setattr(mailer, "send_mail_attachment",
                        lambda to, subject, body, filename, data: sent.append(
                            {"to": to, "subject": subject, "body": body, "filename": filename, "data": data}))
    return sent


def login(client, user: dict) -> None:
    res = client.post("/api/auth/login", json={"login_id": user["login_id"], "password": user["password"]})
    assert res.status_code == 200, res.text


def account_terms(client) -> list[int]:
    return [t["id"] for t in client.get("/api/terms?category=ACCOUNT_OPEN").json() if t["required"]]


def product_id(client, name: str) -> int:
    return next(p["id"] for p in client.get("/api/products").json() if p["product_name"] == name)


def open_account(client, name: str = "기본 입출금통장", **overrides) -> dict:
    body = {"product_id": product_id(client, name), "account_password": "1357", "account_password_confirm": "1357",
            "purpose": "SALARY", "income_source": "SALARY_INCOME", "agreed_term_ids": account_terms(client), **overrides}
    res = client.post("/api/accounts", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def new_user_session(client, outbox, birth: str | None = "1990-05-20", **overrides) -> dict:
    """가입 + 로그인까지 끝낸 사용자. 같은 client의 쿠키에 로그인 상태가 남는다."""
    user = signup_user(client, outbox, birth=birth, **overrides)
    login(client, user)
    return user


def sql(query: str, params=()):
    """테스트 데이터 준비·검증용 직접 SQL."""
    with psycopg.connect(settings.database_url, row_factory=psycopg.rows.dict_row) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None
