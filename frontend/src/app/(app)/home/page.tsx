"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api, fmtDateTime, won, type AccountSummary, type Notification } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";

const STATUS: Record<string, { label: string; tone: "green" | "red" | "amber" }> = {
  ACTIVE: { label: "정상", tone: "green" },
  SUSPENDED: { label: "거래중지", tone: "red" },
  CLOSED: { label: "해지", tone: "amber" },
};

export default function HomePage() {
  const me = useMe();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountSummary[]>("/accounts") });
  const notis = useQuery({ queryKey: ["notifications"], queryFn: () => api<{ items: Notification[] }>("/notifications", { query: { limit: 5 } }) });

  const total = (accounts.data ?? []).filter((a) => a.status !== "CLOSED").reduce((s, a) => s + a.balance, 0);

  async function readAll() {
    await api("/notifications/read-all", { method: "PUT" });
    await qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  return (
    <>
      <PageHeader back={false} title={`${me.data?.user_name ?? ""}님, 안녕하세요`} />
      <main className="space-y-4 p-4">
        <Card className="bg-brand-dark! text-white border-brand-dark!">
          <p className="text-[13px] text-white/70">내 계좌 총 잔액</p>
          <p className="tabular mt-1 text-3xl font-bold">{accounts.data ? won(total) : "…"}</p>
          <div className="mt-4 grid grid-cols-3 gap-2 text-center text-[13px] font-semibold">
            <Link href="/transfer" className="rounded-xl bg-white/15 py-2.5 hover:bg-white/25">이체</Link>
            <Link href="/accounts/new" className="rounded-xl bg-white/15 py-2.5 hover:bg-white/25">계좌 개설</Link>
            <Link href="/cards" className="rounded-xl bg-white/15 py-2.5 hover:bg-white/25">카드</Link>
          </div>
        </Card>

        <section>
          <h2 className="mb-2 text-[15px] font-bold">내 계좌</h2>
          {accounts.isPending ? <Spinner /> : accounts.error ? <ErrorBox error={accounts.error} /> : accounts.data.length === 0 ? (
            <Card><Empty>아직 계좌가 없어요. 계좌를 개설해 보세요.</Empty></Card>
          ) : (
            <div className="space-y-2">
              {accounts.data.map((a) => (
                <Link key={a.id} href={`/accounts/${a.id}`} className="block rounded-2xl border border-line bg-surface p-4 hover:border-brand">
                  <div className="flex items-center justify-between">
                    <p className="text-[13px] text-sub">{a.product_name}{a.is_favorite && " ★"}</p>
                    {STATUS[a.status] && <Badge tone={STATUS[a.status].tone}>{STATUS[a.status].label}</Badge>}
                  </div>
                  <p className="mt-0.5 font-semibold">{a.nickname ?? a.product_name} <span className="text-[13px] font-normal text-sub">{a.account_num_masked}</span></p>
                  <p className="tabular mt-1 text-xl font-bold">{won(a.balance)}</p>
                </Link>
              ))}
            </div>
          )}
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[15px] font-bold">알림</h2>
            <button onClick={readAll} className="text-[12px] text-sub hover:text-brand">모두 읽음</button>
          </div>
          <Card className="divide-y divide-line py-1">
            {notis.data?.items.length ? notis.data.items.map((n) => (
              <div key={n.id} className="py-3">
                <p className={n.read_at ? "text-[13px] text-sub" : "text-[13px] font-medium"}>{n.message}</p>
                <p className="mt-0.5 text-[11px] text-sub">{fmtDateTime(n.created_at)}</p>
              </div>
            )) : <Empty>새 알림이 없어요.</Empty>}
          </Card>
        </section>
      </main>
    </>
  );
}
