"""화면 링크 생성. 링크는 항상 서버가 허용 목록(docs/api-spec.md 7절)에서만 만든다 — 모델이 URL을 쓰지 않는다.

링크에는 사용자가 말한 값(금액·받는 계좌 등)만 미리 채우고 PIN·비밀번호·인증번호는 어떤 링크에도 넣지 않는다.
"""
import uuid
from urllib.parse import urlencode

from app.common.errors import AppError

# screen_id -> (경로 템플릿, 기본 라벨, 허용하는 쿼리 값)
SCREENS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "SCR-001": ("/login", "로그인하기", ()),
    "SCR-002": ("/signup", "회원가입하기", ()),
    "SCR-003": ("/home", "홈으로 가기", ()),
    "SCR-004": ("/accounts/new", "계좌 개설하러 가기", ("product_id",)),
    "SCR-005": ("/accounts/{id}", "계좌 상세 보기", ("from", "to", "type", "q")),
    "SCR-006": ("/transfer", "이체하러 가기", ("from_account_id", "recipient_id", "to_account_num", "amount", "memo")),
    "SCR-007": ("/auto-transfers", "자동이체 화면으로 가기", ("from_account_id", "recipient_id", "to_account_num", "amount", "cycle", "run_day")),
    "SCR-008": ("/cards", "카드 목록 보기", ()),
    "SCR-009": ("/accounts/{id}/manage", "계좌 관리로 가기", ("focus",)),
    "SCR-010": ("/accounts/{id}/close", "계좌 해지 화면으로 가기", ()),
    "SCR-011": ("/cards/{id}", "카드 관리로 가기", ("focus",)),
    "SCR-012": ("/cards/new", "체크카드 발급하러 가기", ("account_id",)),
    "SCR-013": ("/me", "내 정보 관리로 가기", ("focus",)),
    "SCR-014": ("/spending", "소비 리포트 보기", ("month",)),
    "SCR-015": ("/agent", "에이전트 챗", ()),
    "SCR-016": ("/spending/budget", "예산 설정하러 가기", ("month",)),
}
PATH_ID_SCREENS = {"SCR-005", "SCR-009", "SCR-010", "SCR-011"}


def build_link(screen_id: str, *, label: str | None = None, path_id: str | None = None, **params) -> dict:
    if screen_id not in SCREENS:
        raise AppError(500, "INVALID_LINK", "허용되지 않은 화면입니다")
    template, default_label, allowed = SCREENS[screen_id]
    if "{id}" in template:
        try:
            template = template.replace("{id}", str(uuid.UUID(str(path_id))))  # uuid 형식만 허용
        except (ValueError, TypeError):
            raise AppError(500, "INVALID_LINK", "링크 대상이 올바르지 않습니다")
    query = {k: str(v) for k, v in params.items() if v is not None and k in allowed}
    route = template + (("?" + urlencode(query)) if query else "")
    return {"label": label or default_label, "screen_id": screen_id, "route": route}
