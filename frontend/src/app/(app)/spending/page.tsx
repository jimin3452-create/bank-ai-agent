"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmtDateTime, won } from "@/lib/api";
import { Badge, Card, Empty, ErrorBox, PageHeader, Select, Spinner, useToast } from "@/components/ui";
import { MonthPicker, shiftMonth, STATUS_LABEL, thisMonth, type BudgetItem, type Category } from "@/components/spending/common";

type Summary = { month: string; total: number; count: number; card_total: number; card_count: number; transfer_other_total: number; transfer_other_count: number; prev_month: string; prev_total: number; diff: number; diff_rate: number | null };
type ByCat = { month: string; total: number; items: { code: string; name: string; amount: number; count: number; share: number; prev_amount: number; diff: number }[] };
type Merchants = { items: { merchant: string; category: string; category_name: string; amount: number; count: number }[] };
type Daily = { items: { date: string; amount: number; count: number }[] };
type Txs = { total: number; page: number; size: number; items: { id: number; kind: string; merchant: string; name: string; amount: number; at: string; category: string; category_name: string; classified: boolean }[] };
type Compare = { month_a: string; month_b: string; total_a: number; total_b: number; diff: number; diff_rate: number | null; items: { code: string; name: string; amount_a: number; amount_b: number; diff: number; diff_rate: number | null }[] };
type Unclassified = { items: { merchant: string; merchant_key: string; amount: number; count: number }[] };

const diffText = (d: number) => (d === 0 ? "변동 없음" : `${d > 0 ? "+" : "-"}${won(Math.abs(d))}`);
const diffTone = (d: number) => (d > 0 ? "text-danger" : d < 0 ? "text-brand" : "text-sub"); // 지출 증가는 경고색

function SpendingInner() {
  const sp = useSearchParams();
  const raw = sp.get("month");
  const month = raw && /^\d{4}-(0[1-9]|1[0-2])$/.test(raw) ? raw : thisMonth();
  const prev = shiftMonth(month, -1);
  const q = { month };
  const qc = useQueryClient();
  const toast = useToast();
  const [cat, setCat] = useState("");
  const [page, setPage] = useState(1);

  const summary = useQuery({ queryKey: ["sp", "summary", month], queryFn: () => api<Summary>("/spending/summary", { query: q }) });
  const byCat = useQuery({ queryKey: ["sp", "cat", month], queryFn: () => api<ByCat>("/spending/by-category", { query: q }) });
  const merchants = useQuery({ queryKey: ["sp", "top", month], queryFn: () => api<Merchants>("/spending/top-merchants", { query: { ...q, n: 5 } }) });
  const daily = useQuery({ queryKey: ["sp", "daily", month], queryFn: () => api<Daily>("/spending/daily", { query: q }) });
  const compare = useQuery({ queryKey: ["sp", "compare", prev, month], queryFn: () => api<Compare>("/spending/compare", { query: { month_a: prev, month_b: month } }) });
  const txs = useQuery({ queryKey: ["sp", "tx", month, cat, page], queryFn: () => api<Txs>("/spending/transactions", { query: { month, category: cat, page, size: 10 } }) });
  const unclassified = useQuery({ queryKey: ["sp", "unclassified", month], queryFn: () => api<Unclassified>("/spending/unclassified", { query: q }) });
  const categories = useQuery({ queryKey: ["sp", "categories"], queryFn: () => api<Category[]>("/spending/categories"), staleTime: Infinity });
  const budgets = useQuery({ queryKey: ["budgets", month], queryFn: () => api<{ items: BudgetItem[] }>("/budgets", { query: q }) });

  const recat = useMutation({
    mutationFn: (v: { merchant: string; category_code: string }) => api("/spending/merchant-category", { method: "PUT", body: v }),
    onSuccess: async () => {
      toast("카테고리를 바꿨어요");
      await qc.invalidateQueries({ queryKey: ["sp"] });
    },
  });

  const s = summary.data;
  const maxCat = Math.max(1, ...(byCat.data?.items.map((i) => i.amount) ?? [1]));
  const alerts = (budgets.data?.items ?? []).filter((b) => b.status !== "OK");

  return (
    <>
      <PageHeader back={false} title="소비 리포트" right={<Link href={`/spending/budget?month=${month}`} className="px-2 text-sm font-semibold text-brand">예산</Link>} />
      <main className="space-y-4 p-4">
        <MonthPicker month={month} base="/spending" />

        <Card>
          {summary.isPending ? <Spinner /> : summary.error ? <ErrorBox error={summary.error} /> : s && (
            <>
              <p className="text-[13px] text-sub">이번 달 소비 합계</p>
              <p className="tabular mt-1 text-3xl font-bold">{won(s.total)}</p>
              <p className={`mt-1 text-[13px] ${diffTone(s.diff)}`}>
                전월({s.prev_month.slice(5)}월) 대비 {diffText(s.diff)}{s.diff_rate !== null && ` (${s.diff_rate > 0 ? "+" : ""}${s.diff_rate}%)`}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2 text-[13px]">
                <div className="rounded-xl bg-bg p-3"><p className="text-sub">카드 결제</p><p className="tabular font-semibold">{won(s.card_total)}</p><p className="text-[11px] text-sub">{s.card_count}건</p></div>
                <div className="rounded-xl bg-bg p-3"><p className="text-sub">타인 이체</p><p className="tabular font-semibold">{won(s.transfer_other_total)}</p><p className="text-[11px] text-sub">{s.transfer_other_count}건</p></div>
              </div>
              <p className="mt-2 text-[11px] text-sub">소비 = 카드 결제 + 타인 명의 이체 (내 계좌 간 이체는 제외)</p>
            </>
          )}
        </Card>

        {alerts.length > 0 && (
          <Link href={`/spending/budget?month=${month}`} className="block rounded-2xl bg-warn-soft p-4 text-[13px] text-warn">
            <b>예산 알림</b> · {alerts.map((b) => `${b.category_name} ${STATUS_LABEL[b.status]?.label ?? ""}(${Math.round(b.usage_pct)}%)`).join(", ")}
          </Link>
        )}

        <Card>
          <h2 className="mb-3 text-[15px] font-bold">카테고리별</h2>
          {byCat.isPending ? <Spinner /> : !byCat.data?.items.length ? <Empty>이 달 소비 내역이 없어요.</Empty> : (
            <ul className="space-y-3">
              {byCat.data.items.map((c) => (
                <li key={c.code}>
                  <button className="block w-full text-left" onClick={() => { setCat(cat === c.code ? "" : c.code); setPage(1); }}>
                    <div className="flex justify-between text-[13px]">
                      <span className={cat === c.code ? "font-bold text-brand" : ""}>{c.name} <span className="text-sub">{c.share}%</span></span>
                      <span className="tabular font-semibold">{won(c.amount)}</span>
                    </div>
                    <div className="mt-1 h-2 rounded-full bg-brand-soft"><div className="h-full rounded-full bg-brand" style={{ width: `${(c.amount / maxCat) * 100}%` }} /></div>
                    <p className={`mt-0.5 text-[11px] ${diffTone(c.diff)}`}>전월 대비 {diffText(c.diff)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-[15px] font-bold">일별 소비</h2>
          {daily.isPending ? <Spinner /> : !daily.data?.items.length ? <Empty>데이터가 없어요.</Empty> : (
            <div className="h-44" role="img" aria-label="일별 소비 막대 차트">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={daily.data.items.map((d) => ({ day: Number(d.date.slice(8)), amount: d.amount }))}>
                  <CartesianGrid vertical={false} stroke="#e1e9e4" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={11} stroke="#5d6b65" />
                  <YAxis tickLine={false} axisLine={false} fontSize={11} stroke="#5d6b65" width={44} tickFormatter={(v: number) => (v >= 10000 ? `${Math.round(v / 10000)}만` : String(v))} />
                  <Tooltip formatter={(v) => won(Number(v))} labelFormatter={(l) => `${l}일`} cursor={{ fill: "#eaf5ef" }} />
                  <Bar dataKey="amount" name="소비" fill="#16805d" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card>
          <h2 className="mb-1 text-[15px] font-bold">많이 쓴 곳 TOP 5</h2>
          <ol className="divide-y divide-line">
            {merchants.data?.items.map((m, i) => (
              <li key={m.merchant} className="flex items-center justify-between py-2.5 text-[13px]">
                <span><span className="mr-2 text-sub">{i + 1}</span>{m.merchant} <Badge>{m.category_name}</Badge></span>
                <span className="tabular font-semibold">{won(m.amount)}</span>
              </li>
            )) ?? <Spinner />}
          </ol>
        </Card>

        <Card>
          <h2 className="mb-3 text-[15px] font-bold">전월 비교</h2>
          {compare.data && (
            <>
              <p className="mb-2 text-[13px] text-sub">{compare.data.month_a.slice(5)}월 {won(compare.data.total_a)} → {compare.data.month_b.slice(5)}월 {won(compare.data.total_b)}</p>
              <table className="w-full text-[13px]">
                <thead><tr className="text-left text-[11px] text-sub"><th className="pb-1 font-medium">항목</th><th className="pb-1 text-right font-medium">{compare.data.month_a.slice(5)}월</th><th className="pb-1 text-right font-medium">{compare.data.month_b.slice(5)}월</th></tr></thead>
                <tbody>
                  {compare.data.items.map((i) => (
                    <tr key={i.code} className="border-t border-line">
                      <td className="py-2">{i.name}</td>
                      <td className="tabular py-2 text-right text-sub">{i.amount_a.toLocaleString()}</td>
                      <td className="tabular py-2 text-right font-semibold">{i.amount_b.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Card>

        {unclassified.data && unclassified.data.items.length > 0 && (
          <Card>
            <h2 className="text-[15px] font-bold">분류가 필요한 가맹점</h2>
            <p className="mb-2 text-[12px] text-sub">선택한 카테고리는 이후 같은 가맹점 결제에도 적용돼요.</p>
            <ErrorBox error={recat.error} />
            <ul className="divide-y divide-line">
              {unclassified.data.items.map((u) => (
                <li key={u.merchant_key} className="flex items-center justify-between gap-2 py-2.5">
                  <div className="min-w-0 text-[13px]"><p className="truncate font-medium">{u.merchant}</p><p className="tabular text-[11px] text-sub">{won(u.amount)} · {u.count}건</p></div>
                  <Select className="!h-9 !w-32 text-[13px]" aria-label={`${u.merchant} 카테고리`} value="" disabled={recat.isPending} onChange={(e) => e.target.value && recat.mutate({ merchant: u.merchant_key, category_code: e.target.value })}>
                    <option value="">분류 선택</option>
                    {categories.data?.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                  </Select>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[15px] font-bold">소비 내역</h2>
            <Select className="!h-9 !w-36 text-[13px]" aria-label="카테고리 필터" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }}>
              <option value="">전체</option>
              {categories.data?.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </Select>
          </div>
          {txs.isPending ? <Spinner /> : !txs.data?.items.length ? <Empty>내역이 없어요.</Empty> : (
            <>
              <ul className="divide-y divide-line">
                {txs.data.items.map((t) => (
                  <li key={`${t.kind}-${t.id}`} className="flex items-center justify-between py-2.5 text-[13px]">
                    <div className="min-w-0"><p className="truncate font-medium">{t.name}</p><p className="text-[11px] text-sub">{fmtDateTime(t.at)} · {t.classified ? t.category_name : "미분류"}</p></div>
                    <span className="tabular shrink-0 pl-2 font-semibold">{won(t.amount)}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex items-center justify-between text-[13px] text-sub">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-2 py-1">이전</button>
                <span>{page} / {Math.max(1, Math.ceil(txs.data.total / txs.data.size))}</span>
                <button disabled={page >= Math.ceil(txs.data.total / txs.data.size)} onClick={() => setPage(page + 1)} className="px-2 py-1">다음</button>
              </div>
            </>
          )}
        </Card>
      </main>
    </>
  );
}

export default function SpendingPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <SpendingInner />
    </Suspense>
  );
}
