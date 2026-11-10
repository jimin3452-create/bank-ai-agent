from typing import Annotated

from fastapi import APIRouter, Query

from app.common.deps import CurrentUser, Db
from app.spending import service
from app.spending.schemas import BudgetRequest, MerchantCategoryRequest

router = APIRouter(prefix="/api")

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, 없으면 이번 달")]


@router.get("/spending/categories")
def categories(conn: Db, user: CurrentUser):
    return service.list_categories(conn)


@router.get("/spending/summary")
def summary(conn: Db, user: CurrentUser, month: Month = None):
    return service.summary(conn, user["id"], month)


@router.get("/spending/by-category")
def by_category(conn: Db, user: CurrentUser, month: Month = None):
    return service.by_category(conn, user["id"], month)


@router.get("/spending/top-merchants")
def top_merchants(conn: Db, user: CurrentUser, month: Month = None, n: Annotated[int, Query(ge=1, le=20)] = 5):
    return service.top_merchants(conn, user["id"], month, n)


@router.get("/spending/daily")
def daily(conn: Db, user: CurrentUser, month: Month = None):
    return service.daily(conn, user["id"], month)


@router.get("/spending/transactions")
def transactions(conn: Db, user: CurrentUser, month: Month = None, category: str | None = None,
                 page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.transactions(conn, user["id"], month, category, page, size)


@router.get("/spending/compare")
def compare(conn: Db, user: CurrentUser, month_a: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
            month_b: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]):
    return service.compare(conn, user["id"], month_a, month_b)


@router.get("/spending/unclassified")
def unclassified(conn: Db, user: CurrentUser, month: Month = None):
    return service.unclassified(conn, user["id"], month)


@router.put("/spending/merchant-category")
def set_merchant_category(body: MerchantCategoryRequest, conn: Db, user: CurrentUser):
    return service.set_merchant_category(conn, user["id"], body.merchant, body.category_code)


@router.delete("/spending/merchant-category")
def clear_merchant_category(merchant: Annotated[str, Query(min_length=1, max_length=100)], conn: Db, user: CurrentUser):
    return service.clear_merchant_category(conn, user["id"], merchant)


@router.get("/budgets")
def budgets(conn: Db, user: CurrentUser, month: Month = None):
    return service.list_budgets(conn, user["id"], month)


@router.put("/budgets")
def set_budget(body: BudgetRequest, conn: Db, user: CurrentUser):
    return service.set_budget(conn, user["id"], body.month, body.category_code, body.amount)


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int, conn: Db, user: CurrentUser):
    service.delete_budget(conn, user["id"], budget_id)
