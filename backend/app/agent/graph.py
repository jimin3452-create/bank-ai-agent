"""LangGraph 에이전트 그래프 (docs/agent-spec.md 6절).

START -> understand -> plan -> (confirm) -> compose -> finalize -> END

- understand: 모델이 말을 '행동+값'으로 바꾼다. 이전 대화의 값을 이어받고, 되물은 내용에 대한 답을 이어 붙인다.
- plan: 값이 부족하면 되묻고, 아니면 정해진 코드가 도구를 실행한다(조회) / 화면 링크를 만든다 / 쓰기는 확인 카드를 준비한다.
- confirm: 쓰기 동작은 여기서 그래프를 멈추고(interrupt) 사용자가 승인해야 이어서 실행한다. 승인 전에는 DB에 쓰지 않는다.
- compose: 도구 결과로 문장을 만든다(결정적). 모델이 다듬은 문장은 숫자가 맞을 때만 쓴다.
- finalize: 대화 기록(최근 10턴)과 다음 턴에 이어받을 값을 남긴다.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import TypedDict

from fastapi.encoders import jsonable_encoder
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from psycopg import Connection

from app.agent import render, tools
from app.agent.links import build_link
from app.agent.llm import LLM
from app.agent.resolve import Clarify
from app.agent.schemas import LINK_ACTIONS, QUERY_ACTIONS, WRITE_ACTIONS, Understanding
from app.common.errors import AppError
from app.config import settings

MAX_CLARIFY = 2          # 연속으로 되물을 수 있는 횟수. 넘으면 화면 링크로 안내한다
MAX_HISTORY = 20         # 대화 기록 보관 메시지 수(최근 10턴)

FALLBACK_SCREEN = {"GO_TRANSFER": "SCR-006", "GO_AUTO_TRANSFER": "SCR-007", "GO_CARD_MANAGE": "SCR-008", "GO_ISSUE_CARD": "SCR-012",
                   "GO_OPEN_ACCOUNT": "SCR-004", "CARD_PAYMENTS": "SCR-008", "LIST_CARDS": "SCR-008", "SPENDING_SUMMARY": "SCR-014",
                   "SPENDING_BY_CATEGORY": "SCR-014", "SPENDING_TOP_MERCHANTS": "SCR-014", "SPENDING_COMPARE": "SCR-014",
                   "BUDGET_STATUS": "SCR-016", "SET_BUDGET": "SCR-016", "GO_BUDGET_SETTING": "SCR-016", "GO_PROFILE": "SCR-013",
                   "RECATEGORIZE_MERCHANT": "SCR-014"}


class AgentState(TypedDict, total=False):
    user_id: str
    message: str
    history: list          # [{"role": "user"|"assistant", "content": str}]
    understanding: dict
    last: dict | None      # 직전 턴의 {"actions", "slots"} (다음 턴에 이어받을 값)
    needs: dict | None     # 직전에 되물은 내용 {"actions", "slots", "missing"}
    clarify_count: int
    facts: list            # [{"action", "facts", "kind"}]
    evidence: list
    sources: list
    links: list
    pending: dict | None   # 확인을 기다리는 쓰기 동작
    reply: str | None
    degraded: bool


@dataclass
class RunCtx:
    """요청마다 달라지는 실행 환경(체크포인트에 저장하지 않는다)."""
    conn: Connection
    user: dict
    llm: LLM
    today: date


def _tool_ctx(rc: RunCtx) -> tools.Ctx:
    return tools.Ctx(conn=rc.conn, user=rc.user, today=rc.today)


def _home_link() -> list[dict]:
    return [build_link("SCR-003")]


# ---------- 1. 이해 ----------

def understand(state: AgentState, runtime: Runtime[RunCtx]) -> dict:
    rc = runtime.context
    fresh = {"facts": [], "evidence": [], "sources": [], "links": [], "reply": None, "pending": None, "degraded": False}
    hints = {"needs": state.get("needs")}
    try:
        u = rc.llm.understand(state["message"], state.get("history", []), rc.today, hints)
    except Exception:
        return {**fresh, "reply": render.LLM_ERROR, "links": _home_link(), "degraded": True, "understanding": {"actions": []}}

    needs, last = state.get("needs"), state.get("last")
    actions, slots = list(u.actions), u.slots()
    if needs and (not actions or set(actions) <= set(needs["actions"])):
        # 되물은 내용에 대한 답: 이전 요청에 새 값을 합쳐 이어간다
        actions, slots = list(needs["actions"]), {**needs["slots"], **slots}
    elif u.reference_previous_turn and last:
        actions, slots = (actions or list(last["actions"])), {**last["slots"], **slots}
    merged = Understanding.model_validate({**slots, "actions": actions[:2]})
    return {**fresh, "understanding": merged.model_dump(mode="json")}


# ---------- 2. 실행 계획 ----------

def _clarify(state: AgentState, u: Understanding, c: Clarify, rc: RunCtx) -> dict:
    count = state.get("clarify_count", 0) + 1
    if count > MAX_CLARIFY:
        # 같은 정보를 계속 되묻지 않고 화면에서 직접 입력하도록 안내한다
        action = u.actions[0] if u.actions else "SMALLTALK"
        links, text = [], "필요한 내용을 정하지 못했어요. 해당 화면에서 직접 입력해 주세요."
        try:
            if action == "GO_TRANSFER":
                params, _ = tools._transfer_slots(_tool_ctx(rc), u.model_copy(update={"recipient_hint": None}), need=False)
                links = [build_link("SCR-006", label="이체 화면으로 이동", **params)]
            else:
                links = [build_link(FALLBACK_SCREEN.get(action, "SCR-003"))]
        except Exception:
            links = _home_link()
        return {"reply": text, "links": links, "needs": None, "clarify_count": 0, "last": None, "facts": []}
    return {"reply": render.clarify(c.question, c.options), "needs": {"actions": list(u.actions), "slots": u.slots(), "missing": c.missing},
            "clarify_count": count, "facts": [], "links": [], "evidence": [], "sources": []}


def plan(state: AgentState, runtime: Runtime[RunCtx]) -> dict:
    rc = runtime.context
    ctx = _tool_ctx(rc)
    u = Understanding.model_validate(state["understanding"])
    actions = u.actions or ["SMALLTALK"]
    if set(actions) <= {"SMALLTALK", "OUT_OF_SCOPE"}:
        text = render.OUT_OF_SCOPE if "OUT_OF_SCOPE" in actions else render.SMALLTALK
        return {"reply": text, "needs": None, "clarify_count": 0, "facts": [], "links": []}

    facts, evidence, sources, links, pending = [], [], [], [], None
    try:
        for action in actions:
            if action in ("SMALLTALK", "OUT_OF_SCOPE"):
                continue
            if action in WRITE_ACTIONS:
                if pending is None:
                    pending = {**tools.prepare_write(ctx, action, u), "action_id": uuid.uuid4().hex}
                continue
            if action == "KNOWLEDGE_QA":
                res = tools.knowledge_qa(ctx, u, state["message"])
            elif action in QUERY_ACTIONS:
                res = tools.READERS[action](ctx, u)
            elif action in LINK_ACTIONS:
                res = tools.build_links(ctx, action, u)
            else:
                continue
            facts.append({"action": action, "facts": jsonable_encoder(res.facts)})
            evidence += jsonable_encoder(res.evidence)
            sources += jsonable_encoder(res.sources)
            links += res.links
    except Clarify as c:
        return _clarify(state, u, c, rc)
    except AppError as e:
        return {"reply": e.message, "needs": None, "clarify_count": 0, "facts": [], "links": [], "evidence": [], "sources": []}

    seen, uniq = set(), []
    for lk in links:  # 같은 링크가 두 번 나오지 않게
        if lk["route"] not in seen:
            seen.add(lk["route"])
            uniq.append(lk)
    return {"facts": facts, "evidence": evidence[:5], "sources": sources, "links": uniq[:3], "pending": pending, "needs": None,
            "clarify_count": 0, "last": {"actions": list(actions), "slots": u.slots()}}


# ---------- 3. 확인 (쓰기 동작) ----------

def confirm(state: AgentState, runtime: Runtime[RunCtx]) -> dict:
    pending = state["pending"]
    # 여기서 그래프가 멈춘다. 사용자가 승인(True)하거나 거절(False)해야 이어진다. (재개 시 이 함수가 처음부터 다시 실행되므로
    # interrupt 앞에는 부작용이 있는 코드를 두지 않는다.)
    approved = interrupt({"action_id": pending["action_id"], "summary": pending["summary"], "kind": pending["kind"]})
    facts = list(state.get("facts", []))
    if approved:
        result = tools.execute_write(_tool_ctx(runtime.context), pending)
        facts.append({"action": pending["kind"], "facts": jsonable_encoder(result), "kind": "write"})
    else:
        facts.append({"action": "CANCELLED", "facts": {"kind": pending["kind"]}, "kind": "cancel"})
    return {"facts": facts, "pending": None}


# ---------- 4. 답변 만들기 ----------

def compose(state: AgentState, runtime: Runtime[RunCtx]) -> dict:
    if state.get("reply"):
        return {}
    rc = runtime.context
    parts, knowledge_parts = [], []
    for entry in state.get("facts", []):
        a, f = entry["action"], entry["facts"]
        if a == "CANCELLED":
            parts.append("알겠어요. 요청하신 변경은 하지 않았어요.")
        elif entry.get("kind") == "write":
            parts.append(render.render_write(f))
        elif a in LINK_ACTIONS:
            parts.append(render.render_link(f))
        elif a == "KNOWLEDGE_QA":
            knowledge_parts.append(_knowledge_answer(rc, state, f))   # 문서 기반 답변(출처 포함): 다듬기 대상이 아니다
        else:
            parts.append(render.render(a, f))
    draft = "\n\n".join(p for p in parts if p)
    reply = draft
    facts_only = [e["facts"] for e in state.get("facts", []) if e["action"] != "KNOWLEDGE_QA"]
    if draft and settings.agent_polish_reply and not any(e.get("kind") == "cancel" for e in state.get("facts", [])):
        try:
            polished = render.plain_text(rc.llm.compose(state["message"], draft, facts_only, state.get("history", [])))
            no_url = re.search(r"https?://|www\.", polished) is None  # 링크는 서버가 만든 것만 나간다
            ok = bool(polished) and no_url and render.numbers_are_grounded(polished, facts_only, extra=state["message"] + draft)
            if ok:
                reply = polished
        except Exception:
            pass  # 다듬기에 실패해도 결정적 문장으로 답한다
    reply = "\n\n".join(p for p in [reply, *(t for t, _ in knowledge_parts)] if p) or render.SMALLTALK
    out = {"reply": reply}
    used_sources = next((s for _, s in knowledge_parts if s is not None), None)
    if used_sources is not None:  # 응답의 sources에는 답에 실제로 쓴 문서만 담는다
        out["sources"] = used_sources
    return out


USED_LINE = re.compile(r"\n?[ \t]*근거[ \t]*[:：][ \t]*([\d,\s]+?)[ \t]*$")


def _knowledge_answer(rc: RunCtx, state: AgentState, f: dict) -> tuple[str, list[dict] | None]:
    """검색된 문서를 근거로 답한다. 모델 답변은 숫자가 문서와 맞고 링크가 없을 때만 쓰고, 아니면 문서 발췌로 대신한다.

    출처와 안내 문구는 모델이 아니라 서버가 붙인다. 출처는 모델이 '근거: 번호'로 알려 준 문서만 보여 준다(없으면 가장 관련 있는 문서).
    반환: (답변 문장, 답에 쓴 출처 목록 또는 None)
    """
    from app.agent.rag import label
    text, used = None, None
    answer_fn = getattr(rc.llm, "answer_from_passages", None)
    if f.get("found") and answer_fn:
        try:
            ans = answer_fn(state["message"], f["passages"], state.get("history", []))
            if ans:
                m = USED_LINE.search(ans)
                if m:
                    nums = {int(n) for n in re.findall(r"\d+", m.group(1))}
                    used = [i for i in sorted(nums) if 1 <= i <= len(f["passages"])] or None
                    ans = ans[:m.start()]
                ans = render.plain_text(ans)
                no_url = re.search(r"https?://|www\.", ans) is None
                if ans and no_url and render.numbers_are_grounded(ans, f["passages"], extra=state["message"], strict=True):
                    text = ans
        except Exception:
            text, used = None, None  # 모델 호출이 실패해도 문서 발췌로 답한다
    if text is None:
        text, used = render.render("KNOWLEDGE_QA", f), [1] if f.get("found") else None  # 발췌는 첫 문서에서 가져온다
    if "찾지 못했" in text or not f.get("found"):  # 문서로 답하지 못했다고 한 답변에는 출처를 붙이지 않는다
        return text, ([] if f.get("found") else None)
    passages = [f["passages"][i - 1] for i in (used or [1])]
    sources, seen = [], set()
    for p in passages:
        name = label(p)
        if name not in seen:
            seen.add(name)
            sources.append({"title": name, "type": p["type"], "version": p.get("version")})
    footer = render.knowledge_footer({"found": True, "passages": passages}, sources)
    return text + (f"\n\n{footer}" if footer else ""), sources


def finalize(state: AgentState) -> dict:
    history = list(state.get("history", []))
    history += [{"role": "user", "content": state["message"]}, {"role": "assistant", "content": state["reply"]}]
    return {"history": history[-MAX_HISTORY:]}


# ---------- 그래프 ----------

def build_graph(checkpointer):
    g = StateGraph(AgentState, context_schema=RunCtx)
    g.add_node("understand", understand)
    g.add_node("plan", plan)
    g.add_node("confirm", confirm)
    g.add_node("compose", compose)
    g.add_node("finalize", finalize)
    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", lambda s: "compose" if s.get("reply") else "plan", ["compose", "plan"])
    g.add_conditional_edges("plan", lambda s: "confirm" if s.get("pending") else "compose", ["confirm", "compose"])
    g.add_edge("confirm", "compose")
    g.add_edge("compose", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
