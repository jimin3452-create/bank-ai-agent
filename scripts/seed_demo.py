"""가상 회원·계좌·카드·거래 생성 (docs/seed-data.md).

실행 전에 db/001~004와 db/seed/*.sql이 적용되어 있어야 한다.
고정 난수 시드로 매번 같은 데이터를 만들고, 검증용 기대값을 scripts/expected_values.json에 쓴다.
다시 실행하면 데모 회원(demo_a/b/c)의 데이터를 지우고 새로 만든다.

사용: backend/.venv/Scripts/python scripts/seed_demo.py
"""
import base64
import calendar
import json
import os
import random
import secrets
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from argon2 import PasswordHasher
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.types.json import Jsonb

from common import ROOT, connect, load_env

KST = timezone(timedelta(hours=9))
SEED = 20261110
LAST_DAY = date(2026, 11, 9)  # 마지막으로 데이터를 만드는 날짜
MONTHS = [(2026, m) for m in range(5, 12)]
DEMO_LOGIN_IDS = ["demo_a", "demo_b", "demo_c"]

# 월별 (카페, 식비, 지하철·버스, 쇼핑·생활) 건수. 카페는 점점 늘어난다.
CARD_COUNTS = {5: (12, 15, 20, 4), 6: (14, 17, 22, 5), 7: (17, 18, 24, 6),
               8: (19, 20, 26, 7), 9: (22, 22, 27, 6), 10: (25, 25, 28, 8), 11: (8, 12, 7, 2)}

CAFE_BASES = ["스타벅스", "스타벅스", "메가커피", "이디야커피", "투썸플레이스", "파리바게뜨"]
FOOD_BASES = ["맥도날드", "롯데리아", "김밥천국", "본죽", "배달의민족", "맘스터치", "서브웨이", "한솥도시락", "교촌치킨"]
SHOP_BASES = ["쿠팡", "올리브영", "무신사", "다이소"]
LIVING_BASES = ["이마트", "홈플러스", "gs25", "cu"]
UNMAPPED = ["동네수제버거", "달빛서점", "해든한의원", "별빛세탁소", "모두의주차장"]  # 룰에 없는 가맹점(LLM 분류 시연용)

# 지점명 없이 쓰는 가맹점과 표시 이름
NO_BRANCH = {"배달의민족", "쿠팡", "무신사", "넷플릭스", "멜론", "skt통신요금", "카카오t", "티머니", "서울교통공사", "올리브영"}
DISPLAY = {"gs25": "GS25", "cu": "CU", "skt통신요금": "SKT 통신요금", "카카오t": "카카오T", "gs칼텍스": "GS칼텍스"}
BRANCHES = ["강남점", "역삼점", "선릉점", "홍대점"]


def at(d: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=KST)


def luhn_number(rng: random.Random, prefix: str) -> str:
    digits = [int(c) for c in prefix] + [rng.randrange(10) for _ in range(16 - len(prefix) - 1)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    digits.append((10 - total % 10) % 10)
    return "".join(str(d) for d in digits)


def main() -> None:
    load_env()
    for key in ("DEMO_PASSWORD", "DEMO_PIN", "DEMO_ACCOUNT_PASSWORD", "CARD_ENCRYPTION_KEY"):
        if not os.environ.get(key):
            sys.exit(f"{key}가 .env에 없습니다. .env.example을 참고해 채워 주세요.")

    rng = random.Random(SEED)
    hasher = PasswordHasher()
    aes = AESGCM(base64.b64decode(os.environ["CARD_ENCRYPTION_KEY"]))

    def uid() -> uuid.UUID:
        return uuid.UUID(int=rng.getrandbits(128), version=4)

    def display(base: str) -> str:
        name = DISPLAY.get(base, base)
        return name if base in NO_BRANCH else f"{name} {rng.choice(BRANCHES)}"

    with connect() as conn:
        cur = conn.cursor()
        reset(cur)

        # ----- 규칙·카테고리 로드 -----
        cur.execute("SELECT m.merchant_key, c.code FROM merchant_category_map m "
                    "JOIN spending_categories c ON c.id = m.category_id WHERE m.user_id IS NULL")
        rules = dict(cur.fetchall())
        cur.execute("SELECT code, id, name FROM spending_categories")
        categories = {code: (cid, name) for code, cid, name in cur.fetchall()}
        cur.execute("SELECT product_name, id FROM account_products")
        products = dict(cur.fetchall())
        cur.execute("SELECT id, category, required FROM terms")
        terms = cur.fetchall()
        for base in CAFE_BASES + FOOD_BASES + SHOP_BASES + LIVING_BASES + ["넷플릭스", "멜론", "skt통신요금", "티머니", "서울교통공사", "카카오t", "gs칼텍스", "365치과"]:
            assert base in rules, f"가맹점 룰에 없음: {base} (db/seed/03_merchant_rules.sql 확인)"

        # ----- 회원 -----
        pw_hash = hasher.hash(os.environ["DEMO_PASSWORD"])
        pin_hash = hasher.hash(os.environ["DEMO_PIN"])
        acct_pw_hash = hasher.hash(os.environ["DEMO_ACCOUNT_PASSWORD"])
        users = {}
        for login_id, name, birth, email, phone in [
            ("demo_a", "김하늘", date(1999, 3, 15), "demo_a@example.com", "010-0000-0001"),
            ("demo_b", "박서준", date(1990, 7, 20), "demo_b@example.com", "010-0000-0002"),
            ("demo_c", "이신규", None, "demo_c@example.com", "010-0000-0003"),
        ]:
            uid_ = uid()
            created = at(date(2026, 4, 30), 10)
            cur.execute(
                "INSERT INTO users (id, login_id, email, user_name, birth, phone_num, password_hash, pin, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uid_, login_id, email, name, birth, phone, pw_hash, pin_hash, created))
            users[login_id] = {"id": uid_, "name": name}
            for tid, category, required in terms:
                if category == "SIGNUP":
                    cur.execute("INSERT INTO term_agreements (user_id, term_id, agreed, agreed_at) VALUES (%s,%s,%s,%s)",
                                (uid_, tid, required, created))

        # ----- 계좌 -----
        used_nums = set()

        def new_account_num() -> str:
            while True:
                num = f"{rng.randint(100, 999)}-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
                if num not in used_nums:
                    used_nums.add(num)
                    return num

        accounts = {}
        for key, owner, product, nickname, fav, opening in [
            ("A1", "demo_a", "청년 우대 입출금통장", "월급통장", True, {"purpose": "급여", "source": "근로소득"}),
            ("A2", "demo_a", "기본 입출금통장", "비상금", False, {"purpose": "저축", "source": "근로소득"}),
            ("B1", "demo_b", "기본 입출금통장", "생활비", False, {"purpose": "생활비", "source": "근로소득"}),
        ]:
            acc_id, num = uid(), new_account_num()
            created = at(date(2026, 5, 1), 9)
            cur.execute(
                "INSERT INTO accounts (id, user_id, product_id, account_num, account_password, balance, nickname, "
                "is_favorite, opening_info, created_at) VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s,%s)",
                (acc_id, users[owner]["id"], products[product], num, acct_pw_hash, nickname, fav, Jsonb(opening), created))
            accounts[key] = {"id": acc_id, "num": num, "owner": owner}
            for tid, category, required in terms:
                if category == "ACCOUNT_OPEN":
                    cur.execute("INSERT INTO term_agreements (user_id, term_id, agreed, agreed_at) VALUES (%s,%s,%s,%s)",
                                (users[owner]["id"], tid, required, created))

        # ----- 카드 -----
        cards = {}
        for key, acc_key, network, prefix in [("CA", "A1", "VISA", "4"), ("CB", "B1", "LOCAL", "9")]:
            number = luhn_number(rng, prefix + "".join(str(rng.randrange(10)) for _ in range(5)))
            nonce = secrets.token_bytes(12)
            encrypted = base64.b64encode(nonce + aes.encrypt(nonce, number.encode(), None)).decode()
            card_id = uid()
            cur.execute(
                "INSERT INTO cards (id, account_id, card_number, expiry_date, card_network, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (card_id, accounts[acc_key]["id"], encrypted, "05/31", network, at(date(2026, 5, 2), 11)))
            cards[key] = {"id": card_id, "last4": number[-4:], "account": acc_key}

        # ----- 자동이체(월세) -----
        auto_id = uid()
        cur.execute(
            "INSERT INTO auto_transfers (id, from_account_id, to_account_id, amount, memo, cycle, run_day, start_date, "
            "next_run_date, status, created_at) VALUES (%s,%s,%s,%s,%s,'MONTHLY',1,%s,%s,'ACTIVE',%s)",
            (auto_id, accounts["A1"]["id"], accounts["B1"]["id"], 550000, "월세",
             date(2026, 5, 1), date(2026, 12, 1), at(date(2026, 5, 1), 9, 30)))

        # ----- 이벤트 생성 -----
        events = []

        def deposit(acc, dt, amount, who, memo):
            events.append({"t": "deposit", "acc": acc, "dt": dt, "amount": amount, "who": who, "memo": memo})

        def transfer(src, dst, dt, amount, memo, auto=False):
            events.append({"t": "transfer", "src": src, "dst": dst, "dt": dt, "amount": amount, "memo": memo, "auto": auto})

        def card(card_key, dt, base, amount, place):
            events.append({"t": "card", "card": card_key, "dt": dt, "base": base, "amount": amount, "place": place})

        deposit("A1", at(date(2026, 5, 1), 0, 10), 2000000, "초기 입금", "초기 입금")
        deposit("B1", at(date(2026, 5, 1), 0, 10), 5000000, "초기 입금", "초기 입금")

        for y, m in MONTHS:
            first = date(y, m, 1)
            last = min(date(y, m, calendar.monthrange(y, m)[1]), LAST_DAY)
            span = (last - first).days + 1

            def rand_day() -> date:
                return first + timedelta(days=rng.randrange(span))

            def rand_time(d: date) -> datetime:
                return at(d, rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59))

            transfer("A1", "B1", at(first, 9), 550000, "월세", auto=True)
            if m <= 10:
                deposit("A1", at(date(y, m, 25), 9), 2800000, "(주)가상회사", "급여")
                transfer("A1", "A2", at(date(y, m, 26), 10), 300000, "저축")
            for _ in range(rng.randint(1, 2)):
                transfer("A1", "B1", rand_time(rand_day()), rng.randrange(10000, 50001, 5000), "송금")

            n_cafe, n_food, n_metro, n_shop = CARD_COUNTS[m]
            for _ in range(n_cafe):
                base = rng.choice(CAFE_BASES)
                card("CA", rand_time(rand_day()), base, rng.randrange(4000, 7500, 100), display(base))
            if m == 11:  # 진행 중인 달: 식비가 예산(40만원)의 약 80%가 되도록 맞춘다
                while True:
                    amounts = [rng.randrange(15000, 40000, 500) for _ in range(n_food - 1)]
                    rest = 322000 - sum(amounts)
                    if 10000 <= rest <= 60000:
                        amounts.append(rest)
                        break
            else:
                amounts = [rng.randrange(7000, 25000, 500) for _ in range(n_food)]
            for amount in amounts:
                base = rng.choice(FOOD_BASES)
                card("CA", rand_time(rand_day()), base, amount, display(base))
            for _ in range(n_metro):
                base = rng.choice(["티머니", "서울교통공사"])
                card("CA", rand_time(rand_day()), base, rng.choice([1500, 1550]), display(base))
            for _ in range(1 if m == 11 else 2):
                card("CA", rand_time(rand_day()), "카카오t", rng.randrange(9000, 18500, 500), "카카오T")
            card("CA", rand_time(rand_day()), "gs칼텍스", rng.randrange(40000, 60001, 1000), display("gs칼텍스"))
            for i in range(n_shop):
                base = rng.choice(SHOP_BASES if i % 2 == 0 else LIVING_BASES)
                card("CA", rand_time(rand_day()), base, rng.randrange(10000, 120001, 100), display(base))
            for day, base, amount in [(5, "넷플릭스", 17000), (12, "멜론", 10900), (20, "skt통신요금", 55000)]:
                if date(y, m, day) <= last:
                    card("CA", at(date(y, m, day), 3, 0), base, amount, display(base))
            if m == 8:
                card("CA", at(date(y, m, 14), 15, 20), "무신사", 450000, "무신사")
            if m == 10:
                card("CA", at(date(y, m, 18), 11, 40), "365치과", 280000, "365치과 강남점")
                for place, n in [("동네수제버거", 2), ("달빛서점", 1), ("해든한의원", 1)]:
                    for _ in range(n):
                        card("CA", rand_time(rand_day()), None, rng.randrange(8000, 30000, 500), place)
            if m == 11:
                for place in ["별빛세탁소", "모두의주차장", "동네수제버거"]:
                    card("CA", rand_time(rand_day()), None, rng.randrange(5000, 25000, 500), place)

            # demo_b: 소규모 카드 소비
            for _ in range(rng.randint(30, 50) if m != 11 else 12):
                base = rng.choice(CAFE_BASES + FOOD_BASES + LIVING_BASES + ["티머니"])
                card("CB", rand_time(rand_day()), base, rng.randrange(3000, 30001, 500), display(base))

        # ----- 순서대로 원장 기록 -----
        balance = {k: 0 for k in accounts}
        consumption = []   # demo_a 소비: (시각, 카테고리 코드 또는 None, 금액, 종류)
        card_notes = []    # demo_a 카드 결제: (시각, 가맹점, 금액)
        savings_total = defaultdict(int)
        n_transfer = 0

        def ledger(acc_key, tid, cpid, typ, direction, amount, cp_name, cp_acct, memo, dt):
            cur.execute(
                "INSERT INTO account_transactions (account_id, transfer_id, card_payment_id, transaction_type, "
                "transaction_direction, amount, new_balance, counterparty_name, counterparty_account, memo, transaction_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (accounts[acc_key]["id"], tid, cpid, typ, direction, amount, balance[acc_key], cp_name, cp_acct, memo, dt))

        for ev in sorted(events, key=lambda e: e["dt"]):
            ym = (ev["dt"].year, ev["dt"].month)
            if ev["t"] == "deposit":
                balance[ev["acc"]] += ev["amount"]
                ledger(ev["acc"], None, None, "DEPOSIT", "IN", ev["amount"], ev["who"], None, ev["memo"], ev["dt"])
            elif ev["t"] == "transfer":
                src, dst = ev["src"], ev["dst"]
                assert balance[src] >= ev["amount"], f"잔액 부족: {src} {ev['dt']}"
                n_transfer += 1
                tid = uid()
                key = f"auto:{auto_id}:{ev['dt'].date().isoformat()}" if ev["auto"] else f"seed-{n_transfer}"
                cur.execute(
                    "INSERT INTO transfers (id, idempotency_key, from_account_id, to_account_id, auto_transfer_id, amount, "
                    "memo, status, request_at, complete_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'SUCCESS',%s,%s)",
                    (tid, key, accounts[src]["id"], accounts[dst]["id"], auto_id if ev["auto"] else None,
                     ev["amount"], ev["memo"], ev["dt"], ev["dt"] + timedelta(seconds=1)))
                typ = "AUTO_TRANSFER" if ev["auto"] else "TRANSFER"
                balance[src] -= ev["amount"]
                balance[dst] += ev["amount"]
                src_owner, dst_owner = accounts[src]["owner"], accounts[dst]["owner"]
                ledger(src, tid, None, typ, "OUT", ev["amount"], users[dst_owner]["name"], accounts[dst]["num"], ev["memo"], ev["dt"])
                ledger(dst, tid, None, typ, "IN", ev["amount"], users[src_owner]["name"], accounts[src]["num"], ev["memo"], ev["dt"])
                if src_owner == "demo_a":
                    if src_owner != dst_owner:
                        consumption.append((ev["dt"], "TRANSFER", ev["amount"], "TRANSFER_OTHER"))
                    else:
                        savings_total[ym] += ev["amount"]
            else:
                c = cards[ev["card"]]
                acc_key = c["account"]
                assert balance[acc_key] >= ev["amount"], f"잔액 부족: {acc_key} {ev['dt']}"
                cur.execute(
                    "INSERT INTO card_payments (card_id, amount, place, request_at, complete_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (c["id"], ev["amount"], ev["place"], ev["dt"], ev["dt"] + timedelta(seconds=2)))
                cpid = cur.fetchone()[0]
                balance[acc_key] -= ev["amount"]
                ledger(acc_key, None, cpid, "CARD", "OUT", ev["amount"], ev["place"], None, None, ev["dt"])
                if ev["card"] == "CA":
                    consumption.append((ev["dt"], rules.get(ev["base"]) if ev["base"] else None, ev["amount"], "CARD"))
                    card_notes.append((ev["dt"], ev["place"], ev["amount"]))

        for key, acc in accounts.items():
            cur.execute("UPDATE accounts SET balance = %s WHERE id = %s", (balance[key], acc["id"]))

        # ----- 즐겨찾기 받는 계좌, 접속 기록 -----
        cur.execute("INSERT INTO favorite_recipients (user_id, account_num, holder_name, alias) VALUES (%s,%s,%s,%s)",
                    (users["demo_a"]["id"], accounts["B1"]["num"], users["demo_b"]["name"], "서준"))
        for i in range(20):
            d = LAST_DAY - timedelta(days=i + 1 + (i // 2))
            cur.execute("INSERT INTO login_histories (user_id, ip, user_agent, success, created_at) VALUES (%s,%s,%s,true,%s)",
                        (users["demo_a"]["id"], "203.0.113.10", "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 (demo)",
                         at(d, rng.randint(8, 22), rng.randint(0, 59))))

        # ----- 예산, 예산 알림 -----
        def cumulative_alerts(y, m, cat_code, budget):
            """해당 월 소비를 시간순으로 누적해 80%·100% 도달 시각을 구한다."""
            hits, total = {}, 0
            for dt, cat, amount, _ in sorted(consumption, key=lambda r: r[0]):
                if (dt.year, dt.month) != (y, m) or (cat_code and cat != cat_code):
                    continue
                total += amount
                for pct in (80, 100):
                    if pct not in hits and total >= budget * pct / 100:
                        hits[pct] = dt
            return hits, total

        notifications = []
        for y, m in [(2026, 10), (2026, 11)]:
            for cat_code, budget in [("FOOD", 400000), ("CAFE", 100000), (None, 1500000)]:
                hits, _ = cumulative_alerts(y, m, cat_code, budget)
                level = max(hits) if hits else 0
                cat_id = categories[cat_code][0] if cat_code else None
                cur.execute("INSERT INTO budgets (user_id, category_id, budget_month, amount, alert_level) VALUES (%s,%s,%s,%s,%s)",
                            (users["demo_a"]["id"], cat_id, date(y, m, 1), budget, level))
                label = categories[cat_code][1] if cat_code else "월 전체"
                for pct, dt in hits.items():
                    notifications.append((dt + timedelta(seconds=3), "BUDGET_ALERT",
                                          f"{m}월 {label} 예산({budget:,}원)의 {pct}%에 도달했어요.", None))
        for dt, place, amount in sorted(card_notes)[-20:]:
            notifications.append((dt + timedelta(seconds=3), "CARD_PAYMENT",
                                  f"{place}에서 {amount:,}원이 결제되었습니다. (체크카드 {cards['CA']['last4']})",
                                  dt + timedelta(hours=1) if dt.date() < LAST_DAY - timedelta(days=2) else None))
        for created, typ, message, read_at in notifications:
            cur.execute("INSERT INTO notifications (user_id, type, message, read_at, created_at) VALUES (%s,%s,%s,%s,%s)",
                        (users["demo_a"]["id"], typ, message, read_at, created))

        conn.commit()

        # ----- 검증용 기대값 -----
        expected = {}
        for y, m in MONTHS:
            key = f"{y}-{m:02d}"
            rows = [r for r in consumption if (r[0].year, r[0].month) == (y, m)]
            by_cat = defaultdict(int)
            for _, cat, amount, _ in rows:
                by_cat[cat or "UNCLASSIFIED"] += amount
            expected[key] = {
                "total": sum(r[2] for r in rows),
                "card_total": sum(r[2] for r in rows if r[3] == "CARD"),
                "transfer_other_total": sum(r[2] for r in rows if r[3] == "TRANSFER_OTHER"),
                "own_transfer_excluded": savings_total.get((y, m), 0),
                "by_category": dict(sorted(by_cat.items())),
            }
        out = {"user": "demo_a", "seed": SEED, "months": expected,
               "balances": {k: balance[k] for k in accounts}}
        (ROOT / "scripts" / "expected_values.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("완료. 회원 3명, 계좌 3개, 카드 2장")
    print("기말 잔액:", {k: f"{v:,}원" for k, v in balance.items()})
    print("월별 소비(demo_a):", {k: f"{v['total']:,}원" for k, v in expected.items()})


def reset(cur) -> None:
    """데모 회원의 기존 데이터를 지운다(외래키 순서 유의)."""
    cur.execute("SELECT id FROM users WHERE login_id = ANY(%s)", (DEMO_LOGIN_IDS,))
    user_ids = [r[0] for r in cur.fetchall()]
    if not user_ids:
        return
    cur.execute("SELECT id FROM accounts WHERE user_id = ANY(%s)", (user_ids,))
    acc_ids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT id FROM cards WHERE account_id = ANY(%s)", (acc_ids,))
    card_ids = [r[0] for r in cur.fetchall()]
    for sql, arg in [
        ("DELETE FROM notifications WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM login_histories WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM term_agreements WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM budgets WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM agent_messages WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM merchant_category_map WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM favorite_recipients WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM statement_requests WHERE account_id = ANY(%s)", acc_ids),
        ("DELETE FROM account_transactions WHERE account_id = ANY(%s)", acc_ids),
        ("DELETE FROM card_payments WHERE card_id = ANY(%s)", card_ids),
        ("DELETE FROM transfers WHERE from_account_id = ANY(%s) OR to_account_id = ANY(%s)", acc_ids),
        ("DELETE FROM auto_transfers WHERE from_account_id = ANY(%s) OR to_account_id = ANY(%s)", acc_ids),
        ("DELETE FROM cards WHERE account_id = ANY(%s)", acc_ids),
        ("DELETE FROM accounts WHERE user_id = ANY(%s)", user_ids),
        ("DELETE FROM users WHERE id = ANY(%s)", user_ids),
    ]:
        params = (arg, arg) if sql.count("%s") == 2 else (arg,)
        cur.execute(sql, params)


if __name__ == "__main__":
    main()
