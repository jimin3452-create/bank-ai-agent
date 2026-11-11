"use client";

import { useRouter } from "next/navigation";

export type Category = { code: string; name: string };
export type BudgetItem = {
  id: number;
  month: string;
  category_code: string | null;
  category_name: string;
  amount: number;
  spent: number;
  remaining: number;
  usage_pct: number;
  status: "OK" | "WARN" | "OVER" | string;
  alert_level: number;
};

export function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export function shiftMonth(m: string, delta: number) {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(y, mo - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export const monthLabel = (m: string) => `${m.slice(0, 4)}년 ${Number(m.slice(5))}월`;

export function MonthPicker({ month, base }: { month: string; base: string }) {
  const router = useRouter();
  const go = (m: string) => router.replace(`${base}?month=${m}`);
  const isCurrent = month >= thisMonth();
  return (
    <div className="flex items-center justify-between">
      <button aria-label="이전 달" onClick={() => go(shiftMonth(month, -1))} className="h-9 w-9 rounded-full text-xl hover:bg-brand-soft">‹</button>
      <span className="text-[15px] font-bold">{monthLabel(month)}</span>
      <button aria-label="다음 달" disabled={isCurrent} onClick={() => go(shiftMonth(month, 1))} className="h-9 w-9 rounded-full text-xl hover:bg-brand-soft">›</button>
    </div>
  );
}

export function UsageBar({ pct, status }: { pct: number; status: string }) {
  const color = status === "OVER" ? "bg-danger" : status === "WARN" ? "bg-warn" : "bg-brand";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-brand-soft" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}
export const STATUS_LABEL: Record<string, { label: string; tone: "green" | "amber" | "red" }> = {
  OK: { label: "여유", tone: "green" },
  WARN: { label: "주의", tone: "amber" },
  OVER: { label: "초과", tone: "red" },
};
