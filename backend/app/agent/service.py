"""에이전트 서비스: 세션·대화 기록·그래프 실행 (docs/agent-spec.md 6절, docs/decisions.md 5절).

- 대화 맥락은 LangGraph 체크포인터(PostgreSQL)가 세션(스레드)별로 보관하고, 화면에 보여 줄 대화 기록은 agent_messages에 쌓는다.
- 스레드 ID는 `{user_id}:{session_id}`라 다른 회원의 대화에 접근할 수 없다.
- 24시간 동안 대화가 없으면 새 세션으로 시작하고, 기록은 30일 뒤 삭제한다.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agent import render
from app.agent.graph import RunCtx, build_graph
from app.agent.llm import get_llm
from app.common.errors import AppError
from app.config import settings

SESSION_IDLE = timedelta(hours=24)
RETENTION = timedelta(days=30)
MAX_MESSAGE = 1000

_pool: ConnectionPool | None = None
_saver: PostgresSaver | None = None
_graph = None


# ---------- 시작·종료 ----------

def start() -> None:
    """체크포인터(대화 상태 저장소)를 열고 그래프를 만든다. 체크포인터 테이블은 라이브러리가 만든다(setup)."""
    global _pool, _saver, _graph
    _pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=True,
                           kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0})
    _saver = PostgresSaver(_pool)
    _saver.setup()
    _graph = build_graph(_saver)


def stop() -> None:
    global _pool, _saver, _graph
    if _pool is not None:
        _pool.close()
    _pool = _saver = _graph = None


def _need_graph():
    if _graph is None:
        raise AppError(503, "AGENT_UNAVAILABLE", "AI 도우미를 시작하지 못했습니다. 잠시 후 다시 시도해 주세요")
    return _graph


def _thread(user_id, session_id) -> dict:
    return {"configurable": {"thread_id": f"{user_id}:{session_id}"}}


# ---------- 세션 ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned_session(conn: Connection, user_id, session_id) -> dict:
    row = conn.execute("SELECT max(created_at) AS last_at FROM agent_messages WHERE session_id = %s AND user_id = %s",
                       (session_id, user_id)).fetchone()
    if row is None or row["last_at"] is None:
        raise AppError(404, "NOT_FOUND", "대화를 찾을 수 없습니다")
    return row


def _save(conn: Connection, user_id, session_id, role: str, content: str) -> None:
    conn.execute("INSERT INTO agent_messages (user_id, session_id, role, content) VALUES (%s,%s,%s,%s)",
                 (user_id, session_id, role, content))


def list_sessions(conn: Connection, user_id) -> list[dict]:
    return conn.execute(
        "SELECT session_id, max(created_at) AS last_at, "
        "(array_agg(content ORDER BY id) FILTER (WHERE role = 'USER'))[1] AS title FROM agent_messages "
        "WHERE user_id = %s GROUP BY session_id ORDER BY last_at DESC LIMIT 20", (user_id,)).fetchall()


def list_messages(conn: Connection, user_id, session_id) -> list[dict]:
    _owned_session(conn, user_id, session_id)
    return conn.execute("SELECT id, role, content, created_at FROM agent_messages WHERE session_id = %s AND user_id = %s ORDER BY id",
                        (session_id, user_id)).fetchall()


def delete_session(conn: Connection, user_id, session_id) -> None:
    _owned_session(conn, user_id, session_id)
    conn.execute("DELETE FROM agent_messages WHERE session_id = %s AND user_id = %s", (session_id, user_id))
    if _saver is not None:
        _saver.delete_thread(f"{user_id}:{session_id}")


def purge_old_sessions(conn: Connection) -> int:
    """마지막 대화가 30일 지난 세션을 삭제한다(스케줄러가 매일 호출)."""
    rows = conn.execute("SELECT user_id, session_id FROM agent_messages GROUP BY user_id, session_id "
                        "HAVING max(created_at) < %s", (_now() - RETENTION,)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM agent_messages WHERE session_id = %s AND user_id = %s", (r["session_id"], r["user_id"]))
        if _saver is not None:
            _saver.delete_thread(f"{r['user_id']}:{r['session_id']}")
    return len(rows)


# ---------- 대화 ----------

def _pending(cfg: dict) -> dict | None:
    """그래프가 사용자의 승인을 기다리고 있으면 그 요청(action_id, summary)을 돌려준다."""
    state = _need_graph().get_state(cfg)
    for task in state.tasks:
        for it in task.interrupts:
            return it.value
    return None


def _response(session_id, result: dict, *, renewed: bool = False, prefix: str = "") -> dict:
    pending = None
    if result.get("__interrupt__"):
        v = result["__interrupt__"][0].value
        pending = {"action_id": v["action_id"], "summary": v["summary"]}
        reply = v["summary"]
    else:
        reply = result.get("reply") or render.SMALLTALK
    out = {"session_id": str(session_id), "reply": prefix + reply}
    if not pending:
        for key in ("evidence", "sources", "links"):
            if result.get(key):
                out[key] = result[key]
    if pending:
        out["pending_action"] = pending
    if result.get("degraded"):
        out["degraded"] = True
    if renewed:
        out["session_renewed"] = True
    return out


def _run(conn: Connection, user: dict, cfg: dict, payload) -> dict:
    llm = get_llm()
    if llm is None:
        raise AppError(503, "AGENT_UNAVAILABLE", "AI 도우미 설정이 아직 완료되지 않았습니다. 화면 메뉴에서 직접 이용해 주세요")
    ctx = RunCtx(conn=conn, user=user, llm=llm, today=datetime.now(timezone(timedelta(hours=9))).date())
    return _need_graph().invoke(payload, cfg, context=ctx)


def chat(conn: Connection, user: dict, message: str, session_id: uuid.UUID | None) -> dict:
    message = (message or "").strip()
    if not message or len(message) > MAX_MESSAGE:
        raise AppError(400, "VALIDATION_ERROR", f"메시지는 1~{MAX_MESSAGE}자로 입력해 주세요", "message")
    uid, renewed = user["id"], False
    if session_id is None:
        session_id = uuid.uuid4()
    else:
        last = _owned_session(conn, uid, session_id)["last_at"]
        if _now() - last > SESSION_IDLE:  # 오래 쉬었으면 새 대화로 시작
            session_id, renewed = uuid.uuid4(), True
    cfg = _thread(uid, session_id)

    prefix = ""
    if not renewed and _pending(cfg):
        # 확인을 기다리는 요청이 있는데 말로 답한 경우: 승인/거절이면 이어가고, 다른 말이면 이전 요청은 취소한다
        llm = get_llm()
        decision = None
        if llm is not None:
            try:
                u = llm.understand(message, [], datetime.now().date(), {"pending_summary": _pending(cfg)["summary"]})
                decision = u.confirmation
            except Exception:
                decision = None
        if decision in ("YES", "NO"):
            _save(conn, uid, session_id, "USER", message)
            result = _run(conn, user, cfg, Command(resume=(decision == "YES")))
            out = _response(session_id, result)
            _save(conn, uid, session_id, "AGENT", out["reply"])
            return out
        _run(conn, user, cfg, Command(resume=False))
        prefix = "이전에 확인을 기다리던 요청은 취소했어요.\n"

    _save(conn, uid, session_id, "USER", message)
    result = _run(conn, user, cfg, {"user_id": str(uid), "message": message})
    out = _response(session_id, result, renewed=renewed, prefix=prefix)
    _save(conn, uid, session_id, "AGENT", out["reply"])
    return out


def confirm(conn: Connection, user: dict, session_id: uuid.UUID, action_id: str, approve: bool) -> dict:
    uid = user["id"]
    _owned_session(conn, uid, session_id)
    cfg = _thread(uid, session_id)
    pending = _pending(cfg)
    if not pending or pending["action_id"] != action_id:
        raise AppError(409, "NO_PENDING_ACTION", "확인을 기다리는 요청이 없거나 이미 처리되었습니다")
    _save(conn, uid, session_id, "USER", "네, 진행해 주세요" if approve else "아니요, 취소할게요")
    result = _run(conn, user, cfg, Command(resume=approve))
    out = _response(session_id, result)
    _save(conn, uid, session_id, "AGENT", out["reply"])
    return out
