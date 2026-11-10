"""소비 집계 SQL 검증 (docs/agent-spec.md 2절의 집계 기준).

seed_demo.py가 만든 데이터에 집계 SQL을 돌려 scripts/expected_values.json과 비교하고,
거래원장의 잔액 정합성도 확인한다.

사용: backend/.venv/Scripts/python scripts/verify_spending.py
"""
import json
import sys

from common import ROOT, connect, load_env

SPENDING_SQL = """
SELECT to_char(t.transaction_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM') AS month,
       CASE WHEN t.transaction_type = 'CARD' THEN 'CARD' ELSE 'TRANSFER_OTHER' END AS spend_kind,
       SUM(t.amount)::bigint AS total
FROM account_transactions t
JOIN accounts a            ON a.id = t.account_id
LEFT JOIN card_payments cp ON cp.id = t.card_payment_id
LEFT JOIN transfers tr     ON tr.id = t.transfer_id
LEFT JOIN accounts ra      ON ra.id = tr.to_account_id
WHERE a.user_id = %(user_id)s
  AND t.transaction_direction = 'OUT'
  AND (
        (t.transaction_type = 'CARD' AND cp.complete_at IS NOT NULL)
     OR (t.transaction_type IN ('TRANSFER', 'AUTO_TRANSFER')
         AND tr.status = 'SUCCESS' AND ra.user_id <> a.user_id)
      )
GROUP BY 1, 2
"""

OWN_TRANSFER_SQL = """
SELECT to_char(t.transaction_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM') AS month, SUM(t.amount)::bigint
FROM account_transactions t
JOIN accounts a ON a.id = t.account_id
JOIN transfers tr ON tr.id = t.transfer_id
JOIN accounts ra ON ra.id = tr.to_account_id
WHERE a.user_id = %(user_id)s AND t.transaction_direction = 'OUT' AND ra.user_id = a.user_id
GROUP BY 1
"""

CHAIN_SQL = """
SELECT t.account_id, t.id, t.transaction_direction, t.amount, t.new_balance
FROM account_transactions t
ORDER BY t.account_id, t.transaction_at, t.id
"""


def main() -> None:
    load_env()
    expected = json.loads((ROOT / "scripts" / "expected_values.json").read_text(encoding="utf-8"))
    failures = []

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE login_id = %s", (expected["user"],))
        user_id = cur.fetchone()[0]

        # 1) 월별 소비 합계
        cur.execute(SPENDING_SQL, {"user_id": user_id})
        actual = {}
        for month, kind, total in cur.fetchall():
            actual.setdefault(month, {})[kind] = total
        for month, exp in expected["months"].items():
            got_card = actual.get(month, {}).get("CARD", 0)
            got_other = actual.get(month, {}).get("TRANSFER_OTHER", 0)
            ok = (got_card == exp["card_total"] and got_other == exp["transfer_other_total"]
                  and got_card + got_other == exp["total"])
            print(f"{month}  소비 {got_card + got_other:>10,}원  (카드 {got_card:,} + 타인 이체 {got_other:,})  {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"{month}: 기대 {exp['total']:,} / 실제 {got_card + got_other:,}")

        # 2) 본인 계좌 간 이체는 소비에서 제외
        cur.execute(OWN_TRANSFER_SQL, {"user_id": user_id})
        own = dict(cur.fetchall())
        for month, exp in expected["months"].items():
            if own.get(month, 0) != exp["own_transfer_excluded"]:
                failures.append(f"{month}: 본인 계좌 간 이체 합계 불일치")
        print(f"본인 계좌 간 이체(소비 제외): {sum(own.values()):,}원")

        # 3) 거래원장 잔액 정합성
        cur.execute(CHAIN_SQL)
        prev, last_balance, bad = {}, {}, 0
        for account_id, tx_id, direction, amount, new_balance in cur.fetchall():
            before = prev.get(account_id, 0)
            after = before + amount if direction == "IN" else before - amount
            if after != new_balance or new_balance < 0:
                bad += 1
            prev[account_id] = new_balance
        print(f"원장 잔액 연쇄 검사: 어긋난 건 {bad}건")
        if bad:
            failures.append(f"원장 잔액 어긋남 {bad}건")
        cur.execute("SELECT id, balance FROM accounts WHERE user_id IN (SELECT id FROM users WHERE login_id LIKE 'demo_%')")
        for account_id, balance in cur.fetchall():
            if prev.get(account_id, 0) != balance:
                failures.append(f"계좌 잔액과 마지막 원장 잔액 불일치: {account_id}")

    if failures:
        print("\n실패:")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("\n모든 검증 통과")


if __name__ == "__main__":
    main()
