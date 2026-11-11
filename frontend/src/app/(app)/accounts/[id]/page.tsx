"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, fmtDateTime, won, type AccountDetail, type Tx } from "@/lib/api";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, PageHeader, Row, Sheet, Spinner, cx, useToast } from "@/components/ui";

type TxPage = { items: Tx[]; page: number; size: number; total: number; from: string; to: string };
type TxDetail = Tx & { counterparty_account: string | null };

const TYPES: [Tx["type"], string][] = [["DEPOSIT", "입금"], ["WITHDRAW", "출금"], ["TRANSFER", "이체"], ["AUTO_TRANSFER", "자동이체"], ["CARD", "카드"]];
const TYPE_LABEL = Object.fromEntries(TYPES) as Record<string, string>;
const PERIODS = [["1m", "1개월", 1], ["3m", "3개월", 3], ["6m", "6개월", 6], ["12m", "1년", 12]] as const;

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function monthsAgo(n: number) {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return iso(d);
}

function Inner() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const toast = useToast();

  const [period, setPeriod] = useState<string>(sp.get("from") ? "custom" : "3m");
  const [from, setFrom] = useState(sp.get("from") ?? "");
  const [to, setTo] = useState(sp.get("to") ?? "");
  const [types, setTypes] = useState<string[]>(sp.get("type") ? [sp.get("type")!] : []);
  const [dir, setDir] = useState<"ALL" | "IN" | "OUT">("ALL");
  const [qInput, setQInput] = useState(sp.get("q") ?? "");
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [sel, setSel] = useState<number | null>(null);
  const [stmt, setStmt] = useState(false);

  const range = period === "custom" ? { from, to } : { from: monthsAgo(PERIODS.find((p) => p[0] === period)![2]), to: iso(new Date()) };

  const acc = useQuery({ queryKey: ["account", id], queryFn: () => api<AccountDetail>(`/accounts/${id}`) });
  const txs = useInfiniteQuery({
    queryKey: ["transactions", id, range, types, dir, q],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (range.from) qs.set("from", range.from);
      if (range.to) qs.set("to", range.to);
      qs.set("direction", dir);
      types.forEach((t) => qs.append("type", t));
      if (q) qs.set("q", q);
      qs.set("page", String(pageParam));
      qs.set("size", "20");
      return api<TxPage>(`/accounts/${id}/transactions?${qs}`);
    },
    getNextPageParam: (last) => (last.page * last.size < last.total ? last.page + 1 : undefined),
  });
  const items = txs.data?.pages.flatMap((p) => p.items) ?? [];
  const total = txs.data?.pages[0]?.total ?? 0;
  const a = acc.data;
  const blocked = a?.status === "SUSPENDED";

  return (
    <>
      <PageHeader title={a?.nickname ?? a?.product_name ?? "계좌"} back="/home" right={a && a.status !== "CLOSED" ? <Link href={`/accounts/${id}/manage`} className="px-2 text-sm font-semibold text-brand">관리</Link> : undefined} />
      <main className="space-y-4 p-4 pb-10">
        {acc.isPending ? <Spinner /> : acc.error ? <ErrorBox error={acc.error} /> : a && (
          <Card className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-[13px] text-sub">{a.product_name} · 연 {a.interest_rate}%</p>
              {a.status === "ACTIVE" ? <Badge tone="green">정상</Badge> : blocked ? <Badge tone="red">거래중지</Badge> : <Badge tone="amber">해지</Badge>}
            </div>
            <button className="tabular block text-[13px] text-sub" onClick={() => { void navigator.clipboard?.writeText(a.account_num); toast("계좌번호를 복사했어요"); }}>
              {a.account_num} <span className="underline">복사</span>
            </button>
            <p className="tabular text-3xl font-bold">{won(a.balance)}</p>
            {blocked && (
              <div className="rounded-xl bg-danger-soft p-3 text-[13px] text-danger">
                통장 비밀번호를 5회 틀려 거래가 중지되었어요. <Link href={`/accounts/${id}/manage?focus=unlock`} className="font-semibold underline">본인확인으로 해제하기</Link>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <Link href={`/transfer?from_account_id=${id}`} aria-disabled={a.status !== "ACTIVE"} className={cx("grid h-11 place-items-center rounded-xl bg-brand text-sm font-semibold text-white", a.status !== "ACTIVE" && "pointer-events-none opacity-50")}>이체하기</Link>
              <Button variant="ghost" className="h-11 text-sm" onClick={() => setStmt(true)}>거래내역 메일로 받기</Button>
            </div>
          </Card>
        )}

        <section className="space-y-3">
          <h2 className="text-[15px] font-bold">거래내역 <span className="text-[13px] font-normal text-sub">{txs.data ? `총 ${total}건` : ""}</span></h2>
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {PERIODS.map(([k, l]) => <Chip key={k} on={period === k} onClick={() => setPeriod(k)}>{l}</Chip>)}
            <Chip on={period === "custom"} onClick={() => { setPeriod("custom"); setFrom(from || monthsAgo(1)); setTo(to || iso(new Date())); }}>직접</Chip>
          </div>
          {period === "custom" && (
            <div className="flex items-center gap-2">
              <Input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
              <span>~</span>
              <Input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
            </div>
          )}
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {(["ALL", "IN", "OUT"] as const).map((d) => <Chip key={d} on={dir === d} onClick={() => setDir(d)}>{d === "ALL" ? "전체" : d === "IN" ? "입금" : "출금"}</Chip>)}
            <span className="mx-1 w-px shrink-0 bg-line" />
            {TYPES.map(([k, l]) => <Chip key={k} on={types.includes(k)} onClick={() => setTypes((t) => (t.includes(k) ? t.filter((x) => x !== k) : [...t, k]))}>{l}</Chip>)}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); setQ(qInput.trim()); }} className="flex gap-2">
            <Input value={qInput} maxLength={50} placeholder="상대방·메모 검색" onChange={(e) => setQInput(e.target.value)} />
            <Button type="submit" variant="soft" className="shrink-0 px-4">검색</Button>
          </form>

          <Card className="divide-y divide-line py-1">
            {txs.isPending ? <Spinner /> : txs.error ? <ErrorBox error={txs.error} /> : items.length === 0 ? <Empty>조건에 맞는 거래가 없어요.</Empty> : items.map((t) => (
              <Row key={t.id} onClick={() => setSel(t.id)}
                left={<><p className="truncate text-[14px] font-medium">{t.counterparty_name ?? TYPE_LABEL[t.type]}</p><p className="text-[11px] text-sub">{fmtDateTime(t.transaction_at)} · {TYPE_LABEL[t.type]}{t.memo ? ` · ${t.memo}` : ""}</p></>}
                right={<><p className={cx("tabular text-[14px] font-semibold", t.direction === "IN" ? "text-brand" : "text-ink")}>{t.direction === "IN" ? "+" : "-"}{won(t.amount)}</p><p className="tabular text-[11px] text-sub">잔액 {won(t.new_balance)}</p></>} />
            ))}
          </Card>
          {txs.hasNextPage && <Button block variant="ghost" loading={txs.isFetchingNextPage} onClick={() => txs.fetchNextPage()}>더보기</Button>}
        </section>
      </main>

      <TxSheet accountId={id} txId={sel} onClose={() => setSel(null)} />
      <StatementSheet accountId={id} open={stmt} onClose={() => setStmt(false)} />
    </>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" onClick={onClick} className={cx("h-8 shrink-0 rounded-full border px-3.5 text-[13px]", on ? "border-brand bg-brand text-white" : "border-line bg-surface text-sub")}>{children}</button>;
}

function TxSheet({ accountId, txId, onClose }: { accountId: string; txId: number | null; onClose: () => void }) {
  const d = useQuery({ queryKey: ["tx", accountId, txId], queryFn: () => api<TxDetail>(`/accounts/${accountId}/transactions/${txId}`), enabled: txId !== null });
  return (
    <Sheet open={txId !== null} onClose={onClose} title="거래 상세">
      {d.isPending ? <Spinner /> : d.error ? <ErrorBox error={d.error} /> : (
        <dl className="divide-y divide-line text-[14px]">
          {[
            ["구분", `${TYPE_LABEL[d.data.type]} (${d.data.direction === "IN" ? "입금" : "출금"})`],
            ["금액", won(d.data.amount)],
            ["거래 후 잔액", won(d.data.new_balance)],
            ["상대방", d.data.counterparty_name ?? "-"],
            ["상대 계좌", d.data.counterparty_account ?? "-"],
            ["메모", d.data.memo ?? "-"],
            ["일시", fmtDateTime(d.data.transaction_at)],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 py-2.5"><dt className="text-sub">{k}</dt><dd className="tabular text-right font-medium">{v}</dd></div>
          ))}
        </dl>
      )}
    </Sheet>
  );
}

function StatementSheet({ accountId, open, onClose }: { accountId: string; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [from, setFrom] = useState(monthsAgo(1));
  const [to, setTo] = useState(iso(new Date()));
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/accounts/${accountId}/statements`, { method: "POST", body: { from, to } });
      toast("가입한 이메일로 거래내역을 보냈어요");
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet open={open} onClose={onClose} title="거래내역 메일로 받기">
      <div className="space-y-3">
        <p className="text-[13px] text-sub">선택한 기간(최대 1년)의 거래내역을 CSV로 가입한 이메일에 보내 드려요.</p>
        <Field label="시작일"><Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="종료일"><Input type="date" value={to} min={from} max={iso(new Date())} onChange={(e) => setTo(e.target.value)} /></Field>
        <ErrorBox error={err} />
        <Button block loading={busy} disabled={!from || !to} onClick={go}>보내기</Button>
      </div>
    </Sheet>
  );
}

export default function AccountDetailPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Inner />
    </Suspense>
  );
}
