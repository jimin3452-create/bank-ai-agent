"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, fmtDateTime, won, type Card as CardT } from "@/lib/api";
import { Badge, Button, Card, Empty, ErrorBox, MoneyInput, PageHeader, PinSheet, Sheet, Spinner, useToast } from "@/components/ui";

type Detail = CardT & { account_nickname: string | null; used_today: number; remaining_today: number };
type Payments = { items: { id: number; amount: number; place: string; request_at: string; complete_at: string | null }[]; page: number; size: number; total: number };
type Action = "suspend" | "resume" | "lost" | "reissue" | "cancel" | "limit";

const STATUS: Record<string, { label: string; tone: "green" | "amber" | "red" | "gray" }> = {
  ACTIVE: { label: "사용 중", tone: "green" },
  SUSPENDED: { label: "일시정지", tone: "amber" },
  LOST: { label: "분실 신고", tone: "red" },
  REISSUED: { label: "재발급됨", tone: "gray" },
  CANCELED: { label: "해지", tone: "gray" },
};

const ACTIONS: Record<Exclude<Action, "limit">, { label: string; title: string; desc: string; path: string; danger?: boolean; allowed: string[] }> = {
  suspend: { label: "일시정지", title: "카드 일시정지", desc: "카드 결제가 막혀요. 언제든 정지를 해제할 수 있어요.", path: "suspend", allowed: ["ACTIVE"] },
  resume: { label: "정지 해제", title: "정지 해제", desc: "카드를 다시 사용할 수 있게 해요.", path: "resume", allowed: ["SUSPENDED"] },
  lost: { label: "분실 신고", title: "분실 신고", desc: "신고하면 이 카드는 바로 사용할 수 없고 되돌릴 수 없어요. 재발급을 이어서 진행해 주세요.", path: "report-lost", danger: true, allowed: ["ACTIVE", "SUSPENDED"] },
  reissue: { label: "재발급", title: "카드 재발급", desc: "새 카드가 발급되고 기존 카드는 사용할 수 없게 돼요.", path: "reissue", allowed: ["ACTIVE", "SUSPENDED", "LOST"] },
  cancel: { label: "해지", title: "카드 해지", desc: "해지하면 다시 사용할 수 없어요. 계속할까요?", path: "cancel", danger: true, allowed: ["ACTIVE", "SUSPENDED", "LOST"] },
};

export default function Page() {
  return (
    <Suspense fallback={<Spinner />}>
      <CardDetail />
    </Suspense>
  );
}

function CardDetail() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();

  const card = useQuery({ queryKey: ["cards", id], queryFn: () => api<Detail>(`/cards/${id}`) });
  const pays = useQuery({ queryKey: ["cards", id, "payments"], queryFn: () => api<Payments>(`/cards/${id}/payments`, { query: { size: 30 } }) });

  const [action, setAction] = useState<Action | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [limit, setLimit] = useState("");
  const [overseas, setOverseas] = useState(false);

  // 에이전트 링크의 ?focus= 로 해당 동작을 바로 연다(데이터가 처음 도착했을 때 한 번만)
  const focus = sp.get("focus");
  const [focused, setFocused] = useState(false);
  if (card.data && !focused) {
    setFocused(true);
    if (focus === "limit") {
      setLimit(String(card.data.daily_limit));
      setOverseas(card.data.overseas_enabled);
      setAction("limit");
    } else if (focus && focus in ACTIONS && ACTIONS[focus as keyof typeof ACTIONS].allowed.includes(card.data.status)) {
      setAction(focus as Action);
    }
  }

  function open(a: Action) {
    setConfirmed(false);
    setAction(a);
  }
  function openLimit(c: Detail) {
    setLimit(String(c.daily_limit));
    setOverseas(c.overseas_enabled);
    open("limit");
  }
  function close() {
    setAction(null);
    setPinOpen(false);
  }

  async function refresh() {
    await Promise.all([qc.invalidateQueries({ queryKey: ["cards"] }), qc.invalidateQueries({ queryKey: ["accounts"] })]);
  }

  async function submit(pin: string) {
    if (!action) return;
    if (action === "limit") {
      await api(`/cards/${id}/settings`, { method: "PATCH", body: { daily_limit: Number(limit), overseas_enabled: overseas, pin } });
      toast("카드 설정을 변경했어요");
      await refresh();
      setAction(null);
      return;
    }
    const r = await api<{ id?: string }>(`/cards/${id}/${ACTIONS[action].path}`, { method: "POST", body: { pin } });
    toast(`${ACTIONS[action].label}을(를) 완료했어요`);
    await refresh();
    if (action === "reissue" && r?.id) router.replace(`/cards/${r.id}`);
    if (action === "cancel") router.replace("/cards");
  }

  if (card.isPending) return (<><PageHeader title="카드" back="/cards" /><Spinner /></>);
  if (card.error) return (<><PageHeader title="카드" back="/cards" /><div className="p-4"><ErrorBox error={card.error} /></div></>);
  const c = card.data;
  const st = STATUS[c.status] ?? { label: c.status, tone: "gray" as const };
  const available = (Object.keys(ACTIONS) as (keyof typeof ACTIONS)[]).filter((a) => ACTIONS[a].allowed.includes(c.status));
  const limitN = Number(limit || 0);
  const limitErr = limitN < 10_000 || limitN > 10_000_000 ? "일일 한도는 10,000원 ~ 10,000,000원 사이여야 해요." : null;
  const sheetAction = action && action !== "limit" ? ACTIONS[action] : null;

  return (
    <>
      <PageHeader title="카드 관리" back="/cards" />
      <main className="space-y-4 p-4">
        <div className="rounded-2xl bg-gradient-to-br from-brand-dark to-brand p-5 text-white">
          <div className="flex items-center justify-between text-[12px]">
            <span>{c.card_network} 체크카드 · {c.account_nickname ?? "연결 계좌"}</span>
            <Badge tone={st.tone}>{st.label}</Badge>
          </div>
          <p className="tabular mt-6 text-lg tracking-widest">{c.card_number_masked}</p>
          <p className="mt-3 text-[12px] text-white/80">유효기간 {c.expiry_date}</p>
        </div>

        <Card className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-sub">일일 사용한도</span><b className="tabular">{won(c.daily_limit)}</b></div>
          <div className="flex justify-between"><span className="text-sub">오늘 사용</span><span className="tabular">{won(c.used_today)}</span></div>
          <div className="flex justify-between"><span className="text-sub">오늘 남은 한도</span><span className="tabular">{won(c.remaining_today)}</span></div>
          <div className="flex justify-between"><span className="text-sub">해외 결제</span><span>{c.overseas_enabled ? "허용" : "차단"}</span></div>
          {c.status === "ACTIVE" && <Button variant="soft" block className="mt-2 h-10 text-[13px]" onClick={() => openLimit(c)}>한도·해외결제 변경</Button>}
        </Card>

        {available.length > 0 && (
          <div className="grid grid-cols-2 gap-2">
            {available.map((a) => (
              <Button key={a} variant={ACTIONS[a].danger ? "danger" : "ghost"} className="h-11 text-[14px]" onClick={() => open(a)}>{ACTIONS[a].label}</Button>
            ))}
          </div>
        )}

        <section>
          <h2 className="mb-2 text-[15px] font-bold">결제 내역</h2>
          <Card className="divide-y divide-line py-1">
            {pays.isPending ? <Spinner /> : pays.error ? <ErrorBox error={pays.error} /> : pays.data.items.length === 0 ? <Empty>최근 3개월 결제 내역이 없어요.</Empty> : (
              pays.data.items.map((p) => (
                <div key={p.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="text-[14px] font-medium">{p.place}</p>
                    <p className="text-[11px] text-sub">{fmtDateTime(p.request_at)}</p>
                  </div>
                  <p className="tabular font-semibold">-{won(p.amount)}</p>
                </div>
              ))
            )}
          </Card>
        </section>
      </main>

      {/* 설정 변경 */}
      <Sheet open={action === "limit" && !pinOpen} onClose={close} title="한도·해외결제 변경">
        <div className="space-y-4">
          <div>
            <p className="mb-1.5 text-[13px] font-medium text-sub">일일 사용한도</p>
            <MoneyInput value={limit} onChange={setLimit} />
            {limitErr && <p className="mt-1 text-[12px] text-danger">{limitErr}</p>}
          </div>
          <label className="flex items-center justify-between rounded-xl border border-line px-4 py-3">
            <span>해외 결제 허용</span>
            <input type="checkbox" checked={overseas} onChange={(e) => setOverseas(e.target.checked)} className="h-5 w-5 accent-[#16805d]" />
          </label>
          <Button block disabled={!!limitErr} onClick={() => setPinOpen(true)}>PIN으로 변경</Button>
        </div>
      </Sheet>

      {/* 확인 */}
      <Sheet open={!!sheetAction && !confirmed} onClose={close} title={sheetAction?.title ?? ""}>
        <p className="mb-4 text-sm text-sub">{sheetAction?.desc}</p>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="ghost" onClick={close}>취소</Button>
          <Button variant={sheetAction?.danger ? "danger" : "primary"} onClick={() => { setConfirmed(true); setPinOpen(true); }}>계속</Button>
        </div>
      </Sheet>

      <PinSheet
        open={pinOpen}
        onClose={() => { setPinOpen(false); if (action !== "limit") setAction(null); }}
        title="PIN 입력"
        description={action === "limit" ? "카드 설정을 변경합니다." : sheetAction ? `${sheetAction.label}을(를) 진행합니다.` : undefined}
        onSubmit={submit}
      />
    </>
  );
}
