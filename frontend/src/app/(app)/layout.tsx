"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { api, setUnauthorizedHandler, type Notification } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";
import { cx, Spinner } from "@/components/ui";

const IDLE_MS = 10 * 60 * 1000; // 10분 동안 아무 동작이 없으면 로그아웃(docs/decisions.md)

const TABS = [
  { href: "/home", label: "홈", icon: "🏠" },
  { href: "/transfer", label: "이체", icon: "💸" },
  { href: "/spending", label: "소비", icon: "📊" },
  { href: "/agent", label: "에이전트", icon: "💬" },
  { href: "/me", label: "내 정보", icon: "👤" },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const logout = useLogout();
  const me = useMe();

  // 세션 만료(401) → 로그인 화면
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.clear();
      router.replace("/login");
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, router]);
  useEffect(() => {
    if (me.error?.status === 401) router.replace("/login");
  }, [me.error, router]);

  // 유휴 로그아웃
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!me.data) return;
    const reset = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void logout(), IDLE_MS);
    };
    const evs = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    evs.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    reset();
    return () => {
      evs.forEach((e) => window.removeEventListener(e, reset));
      if (timer.current) clearTimeout(timer.current);
    };
  }, [me.data, logout]);

  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api<{ items: Notification[] }>("/notifications", { query: { unread: true, limit: 50 } }),
    enabled: !!me.data,
    refetchInterval: 30_000,
  });

  if (me.isPending) return <Spinner />;
  if (!me.data) return <Spinner label="로그인 화면으로 이동 중…" />;

  const hideTabs = /\/(new|manage|close)$/.test(path) || path.startsWith("/accounts/") || path.startsWith("/cards/");
  return (
    <div className={cx("min-h-dvh", !hideTabs && "pb-20")}>
      {children}
      {!hideTabs && (
        <nav aria-label="주 메뉴" className="fixed inset-x-0 bottom-0 z-30 mx-auto flex h-16 w-full max-w-[430px] border-t border-line bg-surface">
          {TABS.map((t) => {
            const active = path === t.href || (t.href !== "/home" && path.startsWith(t.href));
            return (
              <Link key={t.href} href={t.href} className={cx("relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]", active ? "font-bold text-brand" : "text-sub")}>
                <span className="text-lg leading-none">{t.icon}</span>
                {t.label}
                {t.href === "/home" && (unread.data?.items.length ?? 0) > 0 && <span className="absolute right-[28%] top-2 h-2 w-2 rounded-full bg-danger" />}
              </Link>
            );
          })}
        </nav>
      )}
    </div>
  );
}
