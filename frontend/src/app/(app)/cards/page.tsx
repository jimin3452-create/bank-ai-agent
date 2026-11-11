"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, won, type Card as CardT } from "@/lib/api";
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";

const CARD_STATUS: Record<string, { label: string; tone: "green" | "amber" | "red" | "gray" }> = {
  ACTIVE: { label: "사용 중", tone: "green" },
  SUSPENDED: { label: "일시정지", tone: "amber" },
  LOST: { label: "분실 신고", tone: "red" },
  REISSUED: { label: "재발급됨", tone: "gray" },
  CANCELED: { label: "해지", tone: "gray" },
};

export default function CardsPage() {
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<CardT[]>("/cards") });
  return (
    <>
      <PageHeader title="내 카드" back="/home" />
      <main className="space-y-3 p-4">
        {cards.isPending ? <Spinner /> : cards.error ? <ErrorBox error={cards.error} /> : cards.data.length === 0 ? (
          <Card><Empty>발급된 체크카드가 없어요.</Empty></Card>
        ) : (
          cards.data.map((c) => {
            const st = CARD_STATUS[c.status] ?? { label: c.status, tone: "gray" as const };
            return (
              <Link key={c.id} href={`/cards/${c.id}`} className="block rounded-2xl bg-gradient-to-br from-brand-dark to-brand p-5 text-white shadow-sm">
                <div className="flex items-center justify-between text-[12px]">
                  <span>{c.card_network} 체크카드</span>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
                <p className="tabular mt-6 text-lg tracking-widest">{c.card_number_masked}</p>
                <div className="mt-3 flex justify-between text-[12px] text-white/80">
                  <span>유효기간 {c.expiry_date}</span>
                  <span>일일 한도 {won(c.daily_limit)}</span>
                </div>
              </Link>
            );
          })
        )}
        <Link href="/cards/new" className="grid h-12 place-items-center rounded-xl bg-brand text-[15px] font-semibold text-white">+ 체크카드 발급</Link>
      </main>
    </>
  );
}
