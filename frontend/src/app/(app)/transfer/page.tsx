"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";
import { api, ApiError, newKey, won, type AccountSummary } from "@/lib/api";
import { Badge, Button, Card, ErrorBox, Field, Input, MoneyInput, PageHeader, PinSheet, Select, Spinner, useToast } from "@/components/ui";

type Recent = { account_num: string; account_num_masked: string; holder_name_masked: string };
type Favorite = Recent & { id: number; alias: string | null };
type Lookup = { account_num_masked: string; holder_name_masked: string; is_mine: boolean; can_receive: boolean };
type TransferResult = {
  id: string;
  status: string;
  amount: number;
  memo: string | null;
  to_account_num_masked: string;
  to_holder_masked: string;
  balance_after: number | null;
  replayed: boolean;
};

const fmtNum = (raw: string) => {
  const d = raw.replace(/\D/g, "").slice(0, 11);
  return [d.slice(0, 3), d.slice(3, 7), d.slice(7, 11)].filter(Boolean).join("-");
};

export default function TransferPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <TransferForm />
    </Suspense>
  );
}

function TransferForm() {
  const sp = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountSummary[]>("/accounts") });
  const recents = useQuery({ queryKey: ["recipients", "recent"], queryFn: () => api<Recent[]>("/recipients/recent") });
  const favorites = useQuery({ queryKey: ["recipients", "favorites"], queryFn: () => api<Favorite[]>("/recipients/favorites") });

  const [fromSel, setFromId] = useState(sp.get("from_account_id") ?? "");
  const [toSel, setToNum] = useState<string | null>(sp.get("to_account_num") ? fmtNum(sp.get("to_account_num")!) : null);
  const [amount, setAmount] = useState((sp.get("amount") ?? "").replace(/\D/g, ""));
  const [memo, setMemo] = useState(sp.get("memo") ?? "");
  const [step, setStep] = useState<"form" | "confirm" | "done">("form");
  const [pinOpen, setPinOpen] = useState(false);
  const [result, setResult] = useState<TransferResult | null>(null);
  const [favDone, setFavDone] = useState(false);
  const key = useRef<string | null>(null);

  // 에이전트 링크의 recipient_id(자주 쓰는 계좌) → 계좌번호, 출금 계좌 기본값은 즐겨찾기 → 첫 번째 정상 계좌
  const recipientId = sp.get("recipient_id");
  const prefillNum = recipientId ? favorites.data?.find((x) => String(x.id) === recipientId)?.account_num ?? "" : "";
  const toNum = toSel ?? prefillNum;
  const usable = (accounts.data ?? []).filter((a) => a.status === "ACTIVE");
  const fromId = fromSel || (usable.find((a) => a.is_favorite) ?? usable[0])?.id || "";
  const from = accounts.data?.find((a) => a.id === fromId);

  // 받는 분 확인
  const complete = /^\d{3}-\d{4}-\d{4}$/.test(toNum);
  const lookup = useQuery({
    queryKey: ["lookup", toNum],
    queryFn: () => api<Lookup>("/recipients/lookup", { query: { account_num: toNum } }),
    enabled: complete,
  });

  const amt = Number(amount || 0);
  const lookupErr = lookup.error instanceof ApiError ? lookup.error : null;
  const problem =
    !from ? "출금 계좌를 선택해 주세요." :
    !complete ? "받는 계좌번호를 입력해 주세요." :
    lookup.isPending ? "받는 분을 확인하는 중이에요." :
    lookup.error ? null :
    !lookup.data.can_receive ? "받는 계좌가 입금할 수 없는 상태입니다." :
    amt <= 0 ? "이체 금액을 입력해 주세요." :
    from.balance < amt ? "출금 계좌 잔액이 부족합니다." : null;

  function edit() {
    key.current = null;
    setStep("form");
  }

  function toConfirm() {
    key.current = newKey(); // 이체 한 건(시도)당 키 한 번. 네트워크 오류 재시도 때만 재사용한다.
    setStep("confirm");
  }

  async function send(pin: string) {
    try {
      const r = await api<TransferResult>("/transfers", {
        method: "POST",
        headers: { "Idempotency-Key": key.current! },
        body: { from_account_id: fromId, to_account_num: toNum, amount: amt, memo: memo.trim() || null, pin },
      });
      setResult(r);
      setStep("done");
      void qc.invalidateQueries({ queryKey: ["accounts"] });
      void qc.invalidateQueries({ queryKey: ["recipients"] });
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    } catch (e) {
      // 서버가 응답한 확정 오류(PIN 오류·한도 등)는 새 시도, 연결 문제·5xx는 같은 키로 안전하게 재시도
      if (e instanceof ApiError && e.status > 0 && e.status < 500) key.current = newKey();
      throw e;
    }
  }

  async function addFavorite() {
    try {
      await api("/recipients/favorites", { method: "POST", body: { account_num: toNum } });
      setFavDone(true);
      void qc.invalidateQueries({ queryKey: ["recipients", "favorites"] });
      toast("자주 쓰는 계좌에 등록했어요");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "등록하지 못했어요");
    }
  }

  function reset() {
    setToNum("");
    setAmount("");
    setMemo("");
    setResult(null);
    setFavDone(false);
    key.current = null;
    setStep("form");
  }

  if (accounts.isPending) return (<><PageHeader back={false} title="이체" /><Spinner /></>);

  if (step === "done" && result) {
    const isFav = favorites.data?.some((f) => f.account_num === toNum);
    return (
      <>
        <PageHeader back={false} title="이체 완료" />
        <main className="space-y-4 p-4">
          <Card className="text-center">
            <p className="text-4xl">✅</p>
            <p className="mt-2 text-lg font-bold">{result.to_holder_masked}님께 이체했어요</p>
            <p className="tabular mt-1 text-3xl font-bold text-brand">{won(result.amount)}</p>
            <dl className="mt-4 space-y-1.5 border-t border-line pt-3 text-left text-sm">
              <div className="flex justify-between"><dt className="text-sub">받는 계좌</dt><dd>{result.to_account_num_masked}</dd></div>
              {result.memo && <div className="flex justify-between"><dt className="text-sub">메모</dt><dd>{result.memo}</dd></div>}
              {result.balance_after !== null && <div className="flex justify-between"><dt className="text-sub">출금 후 잔액</dt><dd className="tabular">{won(result.balance_after)}</dd></div>}
            </dl>
            {result.replayed && <p className="mt-3 text-[12px] text-sub">이미 처리된 이체라 다시 보내지 않았어요.</p>}
          </Card>
          {!isFav && !favDone && <Button variant="soft" block onClick={addFavorite}>이 계좌를 자주 쓰는 계좌에 등록</Button>}
          <div className="grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={reset}>다시 이체</Button>
            <Link href="/home" className="grid h-12 place-items-center rounded-xl bg-brand text-[15px] font-semibold text-white">홈으로</Link>
          </div>
        </main>
      </>
    );
  }

  if (step === "confirm" && from && lookup.data) {
    return (
      <>
        <PageHeader back={false} title="이체 확인" />
        <main className="space-y-4 p-4">
          <Card>
            <p className="text-sm text-sub">{lookup.data.holder_name_masked}님께</p>
            <p className="tabular text-3xl font-bold">{won(amt)}</p>
            <dl className="mt-4 space-y-2 border-t border-line pt-3 text-sm">
              <div className="flex justify-between"><dt className="text-sub">출금 계좌</dt><dd>{from.nickname ?? from.product_name} {from.account_num_masked}</dd></div>
              <div className="flex justify-between"><dt className="text-sub">받는 계좌</dt><dd>{lookup.data.account_num_masked}</dd></div>
              <div className="flex justify-between"><dt className="text-sub">출금 후 잔액</dt><dd className="tabular">{won(from.balance - amt)}</dd></div>
              {memo.trim() && <div className="flex justify-between"><dt className="text-sub">메모</dt><dd>{memo.trim()}</dd></div>}
            </dl>
          </Card>
          <p className="text-[12px] text-sub">받는 분 이름과 계좌를 다시 확인해 주세요. 이체 후에는 취소할 수 없어요.</p>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={edit}>수정</Button>
            <Button onClick={() => setPinOpen(true)}>이체하기</Button>
          </div>
        </main>
        <PinSheet open={pinOpen} onClose={() => setPinOpen(false)} title="PIN 입력" description={`${won(amt)}을 이체합니다. PIN 6자리를 입력해 주세요.`} onSubmit={send} />
      </>
    );
  }

  return (
    <>
      <PageHeader back={false} title="이체" />
      <main className="space-y-5 p-4">
        {usable.length === 0 ? (
          <Card className="text-sm">이체할 수 있는 계좌가 없어요. <Link href="/accounts/new" className="font-semibold text-brand">계좌 개설하기</Link></Card>
        ) : (
          <>
            <Field label="출금 계좌" hint={from ? `잔액 ${won(from.balance)}` : undefined}>
              <Select value={fromId} onChange={(e) => setFromId(e.target.value)}>
                {usable.map((a) => <option key={a.id} value={a.id}>{a.nickname ?? a.product_name} · {a.account_num_masked}</option>)}
              </Select>
            </Field>

            <div className="space-y-2">
              <Field label="받는 계좌번호" error={lookupErr?.message}>
                <Input value={toNum} onChange={(e) => setToNum(fmtNum(e.target.value))} inputMode="numeric" placeholder="123-4567-8901" />
              </Field>
              {lookup.data && (
                <p className="flex items-center gap-2 rounded-xl bg-brand-soft px-3.5 py-2.5 text-sm">
                  <span className="font-semibold">{lookup.data.holder_name_masked}</span>
                  <span className="text-sub">{lookup.data.account_num_masked}</span>
                  {lookup.data.is_mine && <Badge tone="green">내 계좌</Badge>}
                  {!lookup.data.can_receive && <Badge tone="red">입금 불가</Badge>}
                </p>
              )}
              <RecipientPicks title="자주 쓰는 계좌" items={favorites.data?.map((f) => ({ ...f, label: f.alias ?? f.holder_name_masked }))} onPick={setToNum} />
              <RecipientPicks title="최근 이체" items={recents.data?.map((r) => ({ ...r, label: r.holder_name_masked }))} onPick={setToNum} />
            </div>

            <Field label="이체 금액">
              <MoneyInput value={amount} onChange={setAmount} />
            </Field>
            <div className="flex gap-2">
              {[10000, 50000, 100000, 500000].map((n) => (
                <button key={n} type="button" onClick={() => setAmount(String(amt + n))} className="flex-1 rounded-lg border border-line bg-surface py-2 text-[12px] font-medium hover:border-brand">
                  +{n >= 10000 ? `${n / 10000}만` : n}
                </button>
              ))}
            </div>
            <Field label="메모 (선택)">
              <Input value={memo} maxLength={100} onChange={(e) => setMemo(e.target.value)} placeholder="받는 분에게 표시돼요" />
            </Field>
            {problem && <p className="text-[13px] text-sub">{problem}</p>}
            <ErrorBox error={null} />
            <Button block disabled={!!problem || !!lookup.error} onClick={toConfirm}>다음</Button>
            <p className="text-center text-[12px]"><Link href="/auto-transfers" className="text-sub hover:text-brand">자동이체 관리 ›</Link></p>
          </>
        )}
      </main>
    </>
  );
}

function RecipientPicks({ title, items, onPick }: { title: string; items?: (Recent & { label: string })[]; onPick: (num: string) => void }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="mb-1 text-[12px] text-sub">{title}</p>
      <div className="flex flex-wrap gap-2">
        {items.map((r) => (
          <button key={r.account_num} type="button" onClick={() => onPick(r.account_num)} className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] hover:border-brand">
            {r.label} <span className="text-sub">{r.account_num_masked.slice(-4)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
