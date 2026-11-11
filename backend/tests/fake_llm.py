"""테스트용 가짜 모델. 정해 둔 '말 -> 이해 결과' 표대로만 답한다(모델의 판단 품질이 아니라 그래프의 동작을 검증하기 위한 것)."""
from datetime import date

from app.agent.schemas import Understanding


class ScriptedLLM:
    def __init__(self):
        self.table: dict[str, Understanding] = {}
        self.calls: list[dict] = []          # understand에 전달된 내용(도구 결과가 섞여 들어가지 않는지 확인용)
        self.compose_calls: list[dict] = []
        self.fail_understand = False
        self.compose_fn = None                # (draft) -> 다듬은 문장. None이면 초안 그대로
        self.answer_fn = None                 # (message, passages) -> 문서 기반 답변. None이면 모델 답변 없음(문서 발췌로 대신)
        self.answer_calls: list[dict] = []

    def say(self, message: str, **kw) -> "ScriptedLLM":
        self.table[message] = Understanding(**kw)
        return self

    def understand(self, message: str, history: list[dict], today: date, hints: dict) -> Understanding:
        self.calls.append({"message": message, "history": list(history), "hints": hints})
        if self.fail_understand:
            raise RuntimeError("LLM down")
        found = self.table.get(message)
        return found.model_copy(deep=True) if found else Understanding(actions=["OUT_OF_SCOPE"])

    def compose(self, message: str, draft: str, facts: list, history: list[dict]) -> str:
        self.compose_calls.append({"message": message, "draft": draft, "facts": facts})
        if self.compose_fn is None:
            return draft
        return self.compose_fn(draft)

    def answer_from_passages(self, message: str, passages: list[dict], history: list[dict]):
        self.answer_calls.append({"message": message, "passages": passages})
        if self.answer_fn is None:
            return None
        return self.answer_fn(message, passages)
