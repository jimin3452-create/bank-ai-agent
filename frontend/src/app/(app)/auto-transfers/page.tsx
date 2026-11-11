"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, fmtDate, won, type AccountSummary } from "@/lib/api";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, MoneyInput, PageHeader, PinSheet, Select, Sheet, Spinner, useToast } from "@/components/ui";

type Auto = {
  id: string;
  from_account_id: string;
  to_account_num_masked: string;
  to_holder_masked: string;
  amount: number;
  memo: string | null;
  cycle: "WEEKLY" | "MONTHLY";
  run_day: number;
  start_date: string;
  end_date: string | null;
  next_run_date: string | null;
  status: string;
  last_result: string | null;
  last_run_at: string | null;
  last_fail_reason: string | null;
};
type Favorite = { id: number; account_num: string; account_num_masked: string; holder_name_masked: string; alias: string | null };

const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
const cycleText = (a: Pick<Auto, "cycle" | "run_day">) => (a.cycle === "MONTHLY" ? `매월 ${a.run_day}일` : `매주 ${DAYS[a.run_day]}요일`);
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const tomorrow = () => iso(new Date(Date.now() + 86400000));
const fmtNum = (raw: string) => {
  const d = raw.replace(/\D/g, "").slice(0, 11);
  return [d.slice(0, 3), d.slice(3, 7), d.slice(7, 11)].filter(Boolean).join("-");
};

export default function Page() {
  return (
    <Suspense fallback={<Spinner />}>
      <AutoTransfers />
    </Suspense>
  );
}

function AutoTransfers() {
  const sp = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["auto-transfers"], queryFn: () => api<Auto[]>("/auto-transfers") });
  const hasPrefill = ["from_account_id", "recipient_id", "to_account_num", "amount", "cycle", "run_day"].some((k) => sp.get(k));
  const [formOpen, setFormOpen] = useState(hasPrefill);
  const [cancelId, setCancelId] = useState<string | null>(null);

  async function cancel(pin: string) {
    await api(`/auto-transfers/${cancelId}/cancel`, { method: "POST", body: { pin } });
    await qc.invalidateQueries({ queryKey: ["auto-transfers"] });
    toast("자동이체를 해지했어요");
  }

  return (
    <>
      <PageHeader title="자동이체" back="/transfer" right={<Button className="h-9 px-3 text-[13px]" onClick={() => setFormOpen(true)}>+ 등록</Button>} />
      <main className="space-y-3 p-4">
        {list.isPending ? <Spinner /> : list.error ? <ErrorBox error={list.error} /> : list.data.length === 0 ? (
          <Card><Empty>등록된 자동이체가 없어요.</Empty></Card>
        ) : (
          list.data.map((a) => (
            <Card key={a.id}>
              <div className="flex items-center justify-between">
                <p className="font-semibold">{a.to_holder_masked} <span className="text-[13px] font-normal text-sub">{a.to_account_num_masked}</span></p>
                <Badge tone={a.status === "ACTIVE" ? "green" : "gray"}>{a.status === "ACTIVE" ? "사용 중" : "해지"}</Badge>
              </div>
              <p className="tabular mt-1 text-xl font-bold">{won(a.amount)}</p>
              <p className="mt-1 text-[13px] text-sub">{cycleText(a)}{a.memo && ` · ${a.memo}`}</p>
              <p className="text-[12px] text-sub">기간 {a.start_date} ~ {a.end_date ?? "종료일 없음"}</p>
              {a.status === "ACTIVE" && a.next_run_date && <p className="mt-1 text-[13px]">다음 이체일 <b>{a.next_run_date}</b></p>}
              {a.last_result && (
                <p className={`mt-1 text-[12px] ${a.last_result === "SUCCESS" ? "text-sub" : "text-danger"}`}>
                  최근 실행 {a.last_run_at ? fmtDate(a.last_run_at) : ""} · {a.last_result === "SUCCESS" ? "성공" : `실패${a.last_fail_reason ? ` (${a.last_fail_reason})` : ""}`}
                </p>
              )}
              {a.status === "ACTIVE" && <Button variant="ghost" className="mt-3 h-10 w-full text-[13px]" onClick={() => setCancelId(a.id)}>해지</Button>}
            </Card>
          ))
        )}
      </main>
      <CreateSheet open={formOpen} onClose={() => setFormOpen(false)} />
      <PinSheet open={!!cancelId} onClose={() => setCancelId(null)} title="자동이체 해지" description="PIN을 입력하면 이 자동이체가 해지돼요." onSubmit={cancel} />
    </>
  );
}

function CreateSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const sp = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountSummary[]>("/accounts") });
  const favorites = useQuery({ queryKey: ["recipients", "favorites"], queryFn: () => api<Favorite[]>("/recipients/favorites") });
  const usable = (accounts.data ?? []).filter((a) => a.status === "ACTIVE");

  const [fromSel, setFromId] = useState(sp.get("from_account_id") ?? "");
  const [toSel, setToNum] = useState<string | null>(sp.get("to_account_num") ? fmtNum(sp.get("to_account_num")!) : null);
  const [amount, setAmount] = useState((sp.get("amount") ?? "").replace(/\D/g, ""));
  const [memo, setMemo] = useState("");
  const [cycle, setCycle] = useState<"WEEKLY" | "MONTHLY">(sp.get("cycle") === "WEEKLY" ? "WEEKLY" : "MONTHLY");
  const [runDay, setRunDay] = useState(sp.get("run_day") ?? (cycle === "MONTHLY" ? "1" : "0"));
  const [start, setStart] = useState(tomorrow());
  const [end, setEnd] = useState("");
  const [pinOpen, setPinOpen] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const recipientId = sp.get("recipient_id");
  const prefillNum = recipientId ? favorites.data?.find((x) => String(x.id) === recipientId)?.account_num ?? "" : "";
  const toNum = toSel ?? prefillNum;
  const fromId = fromSel || usable[0]?.id || "";

  function changeCycle(c: "WEEKLY" | "MONTHLY") {
    setCycle(c);
    setRunDay(c === "MONTHLY" ? "1" : "0");
  }

  const dayNum = Number(runDay);
  const dayOk = cycle === "MONTHLY" ? dayNum >= 1 && dayNum <= 31 : dayNum >= 0 && dayNum <= 6;
  const dateErr = start < tomorrow() ? "시작일은 내일 이후여야 해요." : end && end < start ? "종료일은 시작일보다 빠를 수 없어요." : null;
  const ok = !!fromId && /^\d{3}-\d{4}-\d{4}$/.test(toNum) && Number(amount) > 0 && dayOk && !dateErr;

  async function create(pin: string) {
    setErr(null);
    try {
      await api("/auto-transfers", {
        method: "POST",
        body: { from_account_id: fromId, to_account_num: toNum, amount: Number(amount), memo: memo.trim() || null, cycle, run_day: dayNum, start_date: start, end_date: end || null, pin },
      });
    } catch (e) {
      setErr(e);
      throw e;
    }
    await qc.invalidateQueries({ queryKey: ["auto-transfers"] });
    toast("자동이체를 등록했어요");
    onClose();
  }

  return (
    <>
      <Sheet open={open && !pinOpen} onClose={onClose} title="자동이체 등록">
        <div className="space-y-4">
          <Field label="출금 계좌">
            <Select value={fromId} onChange={(e) => setFromId(e.target.value)}>
              {usable.map((a) => <option key={a.id} value={a.id}>{a.nickname ?? a.product_name} · {a.account_num_masked}</option>)}
            </Select>
          </Field>
          <Field label="받는 계좌번호">
            <Input value={toNum} inputMode="numeric" placeholder="123-4567-8901" onChange={(e) => setToNum(fmtNum(e.target.value))} />
          </Field>
          {favorites.data && favorites.data.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {favorites.data.map((f) => (
                <button key={f.id} type="button" onClick={() => setToNum(f.account_num)} className="rounded-full border border-line px-3 py-1.5 text-[13px] hover:border-brand">{f.alias ?? f.holder_name_masked}</button>
              ))}
            </div>
          )}
          <Field label="금액"><MoneyInput value={amount} onChange={setAmount} /></Field>
          <Field label="메모 (선택)"><Input value={memo} maxLength={100} onChange={(e) => setMemo(e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="주기">
              <Select value={cycle} onChange={(e) => changeCycle(e.target.value as "WEEKLY" | "MONTHLY")}>
                <option value="MONTHLY">매월</option>
                <option value="WEEKLY">매주</option>
              </Select>
            </Field>
            <Field label={cycle === "MONTHLY" ? "실행일" : "요일"}>
              {cycle === "MONTHLY" ? (
                <Select value={runDay} onChange={(e) => setRunDay(e.target.value)}>
                  {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}일</option>)}
                </Select>
              ) : (
                <Select value={runDay} onChange={(e) => setRunDay(e.target.value)}>
                  {DAYS.map((d, i) => <option key={d} value={i}>{d}요일</option>)}
                </Select>
              )}
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="시작일" error={dateErr}><Input type="date" min={tomorrow()} value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="종료일 (선택)"><Input type="date" min={start} value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <p className="text-[12px] text-sub">시작일은 내일 이후만 가능하고, 최대 10건까지 등록할 수 있어요. 31일은 해당 일이 없는 달에는 말일에 실행돼요.</p>
          <ErrorBox error={err} />
          <Button block disabled={!ok} onClick={() => setPinOpen(true)}>PIN으로 등록</Button>
        </div>
      </Sheet>
      <PinSheet open={open && pinOpen} onClose={() => setPinOpen(false)} title="PIN 입력" description="자동이체를 등록합니다." onSubmit={create} />
    </>
  );
}
