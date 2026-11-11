"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, won, type AccountSummary, type Card as CardT } from "@/lib/api";
import { Button, Card, ErrorBox, Field, Input, MoneyInput, PageHeader, Select, Spinner } from "@/components/ui";

function useRun() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [out, setOut] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>, fmt: (r: never) => string) {
    setBusy(true);
    setErr(null);
    setOut(null);
    try {
      setOut(fmt((await fn()) as never));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  return { busy, err, out, run };
}

export default function DevPage() {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountSummary[]>("/accounts") });
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<CardT[]>("/cards") });
  const refresh = () => Promise.all(["accounts", "cards", "notifications", "spending", "budgets"].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  const pay = useRun();
  const [cardId, setCardId] = useState("");
  const [place, setPlace] = useState("스타벅스 강남점");
  const [payAmt, setPayAmt] = useState("5500");
  const [overseas, setOverseas] = useState(false);

  const dep = useRun();
  const [accId, setAccId] = useState("");
  const [depAmt, setDepAmt] = useState("100000");
  const [from, setFrom] = useState("시연 입금");

  const auto = useRun();
  const [today, setToday] = useState("");

  if (accounts.isPending || cards.isPending) return (<><PageHeader title="개발용 시뮬레이터" /><Spinner /></>);
  const activeCards = (cards.data ?? []).filter((c) => c.status === "ACTIVE");
  const cid = cardId || activeCards[0]?.id || "";
  const aid = accId || accounts.data?.[0]?.id || "";

  return (
    <>
      <PageHeader title="개발용 시뮬레이터" back="/home" />
      <main className="space-y-4 p-4">
        <p className="rounded-xl bg-warn-soft px-3.5 py-3 text-[12px] text-warn">시연을 위한 화면이에요. 서버가 개발 모드(APP_ENV=dev)일 때만 동작해요.</p>

        <Card className="space-y-3">
          <h2 className="font-bold">카드 결제</h2>
          <Field label="카드">
            <Select value={cid} onChange={(e) => setCardId(e.target.value)}>
              {activeCards.map((c) => <option key={c.id} value={c.id}>{c.card_number_masked.slice(-4)} · {c.card_network}</option>)}
            </Select>
          </Field>
          <Field label="가맹점"><Input value={place} onChange={(e) => setPlace(e.target.value)} /></Field>
          <Field label="금액"><MoneyInput value={payAmt} onChange={setPayAmt} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={overseas} onChange={(e) => setOverseas(e.target.checked)} className="accent-[#16805d]" /> 해외 결제</label>
          <ErrorBox error={pay.err} />
          {pay.out && <p className="text-sm text-brand">{pay.out}</p>}
          <Button block loading={pay.busy} disabled={!cid || !place.trim() || !Number(payAmt)} onClick={() =>
            pay.run(async () => { const r = await api("/dev/card-payments", { method: "POST", body: { card_id: cid, amount: Number(payAmt), place: place.trim(), overseas } }); await refresh(); return r; },
              (r: { place: string; amount: number; balance_after: number }) => `${r.place} ${won(r.amount)} 결제됨 · 잔액 ${won(r.balance_after)}`)}>결제하기</Button>
        </Card>

        <Card className="space-y-3">
          <h2 className="font-bold">입금</h2>
          <Field label="계좌">
            <Select value={aid} onChange={(e) => setAccId(e.target.value)}>
              {accounts.data?.filter((a) => a.status !== "CLOSED").map((a) => <option key={a.id} value={a.id}>{a.nickname ?? a.product_name} · {a.account_num_masked}</option>)}
            </Select>
          </Field>
          <Field label="입금자"><Input value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="금액"><MoneyInput value={depAmt} onChange={setDepAmt} /></Field>
          <ErrorBox error={dep.err} />
          {dep.out && <p className="text-sm text-brand">{dep.out}</p>}
          <Button block loading={dep.busy} disabled={!aid || !Number(depAmt)} onClick={() =>
            dep.run(async () => { const r = await api("/dev/deposits", { method: "POST", body: { account_id: aid, amount: Number(depAmt), counterparty_name: from.trim() || "시연 입금" } }); await refresh(); return r; },
              (r: { balance: number }) => `입금 완료 · 잔액 ${won(r.balance)}`)}>입금하기</Button>
        </Card>

        <Card className="space-y-3">
          <h2 className="font-bold">자동이체 지금 실행</h2>
          <Field label="기준 날짜 (비우면 오늘)"><Input type="date" value={today} onChange={(e) => setToday(e.target.value)} /></Field>
          <ErrorBox error={auto.err} />
          {auto.out && <p className="text-sm text-brand">{auto.out}</p>}
          <Button block loading={auto.busy} onClick={() =>
            auto.run(async () => { const r = await api("/dev/run-auto-transfers", { method: "POST", body: { today: today || null } }); await refresh(); await qc.invalidateQueries({ queryKey: ["auto-transfers"] }); return r; },
              (r: unknown[]) => `${Array.isArray(r) ? r.length : 0}건 처리됨`)}>실행</Button>
        </Card>
      </main>
    </>
  );
}
