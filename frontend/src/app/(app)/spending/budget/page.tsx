"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, won } from "@/lib/api";
import { Badge, Button, Card, Empty, ErrorBox, Field, MoneyInput, PageHeader, Select, Spinner, useToast } from "@/components/ui";
import { MonthPicker, STATUS_LABEL, thisMonth, UsageBar, type BudgetItem, type Category } from "@/components/spending/common";

function BudgetInner() {
  const sp = useSearchParams();
  const raw = sp.get("month");
  const month = raw && /^\d{4}-(0[1-9]|1[0-2])$/.test(raw) ? raw : thisMonth();
  const qc = useQueryClient();
  const toast = useToast();
  const [cat, setCat] = useState(""); // "" = 월 전체
  const [amount, setAmount] = useState("");

  const budgets = useQuery({ queryKey: ["budgets", month], queryFn: () => api<{ items: BudgetItem[] }>("/budgets", { query: { month } }) });
  const categories = useQuery({ queryKey: ["sp", "categories"], queryFn: () => api<Category[]>("/spending/categories"), staleTime: Infinity });

  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["budgets"] }), qc.invalidateQueries({ queryKey: ["sp"] })]);
  const save = useMutation({
    mutationFn: () => api("/budgets", { method: "PUT", body: { month, category_code: cat || null, amount: Number(amount) } }),
    onSuccess: async () => { toast("예산을 저장했어요"); setAmount(""); await refresh(); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/budgets/${id}`, { method: "DELETE" }),
    onSuccess: async () => { toast("예산을 삭제했어요"); await refresh(); },
  });

  return (
    <>
      <PageHeader title="예산 설정" back={`/spending?month=${month}`} />
      <main className="space-y-4 p-4">
        <MonthPicker month={month} base="/spending/budget" />
        <ErrorBox error={del.error} />
        {budgets.isPending ? <Spinner /> : budgets.error ? <ErrorBox error={budgets.error} /> : !budgets.data.items.length ? (
          <Card><Empty>이 달에 설정한 예산이 없어요.</Empty></Card>
        ) : (
          <div className="space-y-2">
            {budgets.data.items.map((b) => (
              <Card key={b.id}>
                <div className="flex items-center justify-between">
                  <p className="font-semibold">{b.category_name} {STATUS_LABEL[b.status] && <Badge tone={STATUS_LABEL[b.status].tone}>{STATUS_LABEL[b.status].label}</Badge>}</p>
                  <button onClick={() => confirm(`${b.category_name} 예산을 삭제할까요?`) && del.mutate(b.id)} className="text-[12px] text-sub hover:text-danger">삭제</button>
                </div>
                <div className="my-2"><UsageBar pct={b.usage_pct} status={b.status} /></div>
                <div className="tabular flex justify-between text-[12px] text-sub">
                  <span>{won(b.spent)} / {won(b.amount)} ({b.usage_pct}%)</span>
                  <span>{b.remaining >= 0 ? `${won(b.remaining)} 남음` : `${won(-b.remaining)} 초과`}</span>
                </div>
              </Card>
            ))}
          </div>
        )}

        <Card>
          <h2 className="mb-3 text-[15px] font-bold">예산 설정·수정</h2>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Field label="대상">
              <Select value={cat} onChange={(e) => setCat(e.target.value)}>
                <option value="">월 전체</option>
                {categories.data?.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="예산 금액" hint="같은 대상의 예산이 있으면 금액을 덮어써요. 사용률이 80%·100%가 되면 알림이 가요.">
              <MoneyInput value={amount} onChange={setAmount} />
            </Field>
            <ErrorBox error={save.error} />
            <Button type="submit" block loading={save.isPending} disabled={!amount || Number(amount) <= 0}>저장</Button>
          </form>
        </Card>
      </main>
    </>
  );
}

export default function BudgetPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <BudgetInner />
    </Suspense>
  );
}
