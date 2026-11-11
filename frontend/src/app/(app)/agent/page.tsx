"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, fmtDateTime, type AgentLink, type AgentReply } from "@/lib/api";
import { Button, ErrorBox, PageHeader, Sheet, cx } from "@/components/ui";

type Source = { title: string; type?: string; version?: string | null };
type Msg = {
  id: string;
  role: "user" | "agent";
  text: string;
  links?: AgentLink[];
  sources?: Source[];
  notice?: string;
  pending?: { action_id: string; summary: string } | null;
  resolved?: boolean;
};
type Session = { session_id: string; last_at: string; title: string };
type StoredMsg = { id: number; role: "USER" | "AGENT"; content: string; created_at: string };

const SUGGESTIONS = ["이번 달 카페에 얼마 썼어?", "식비 예산 40만원으로 설정해줘", "서준한테 5만원 보내줘", "청년 통장 가입 조건이 뭐야?", "거래중지는 어떻게 풀어?", "카드 분실했어"];
let seq = 0;
const mid = () => `m${Date.now()}-${seq++}`;

export default function AgentPage() {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [listOpen, setListOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const sessions = useQuery({ queryKey: ["agent", "sessions"], queryFn: () => api<Session[]>("/agent/sessions"), enabled: listOpen });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  function applyReply(r: AgentReply) {
    setSessionId(r.session_id);
    const notice = [r.session_renewed && "이전 대화가 오래되어 새 대화로 시작했어요.", r.degraded && "지금은 자연어 이해가 원활하지 않아요. 아래 화면 바로가기를 이용하거나 잠시 후 다시 시도해 주세요."].filter(Boolean).join(" ");
    setMsgs((m) => [
      ...m,
      { id: mid(), role: "agent", text: r.reply, links: r.links, sources: r.sources as Source[] | undefined, pending: r.pending_action ?? null, notice: notice || undefined },
    ]);
    void qc.invalidateQueries({ queryKey: ["agent", "sessions"] });
  }

  async function send(text: string) {
    const t = text.trim();
    if (!t || busy) return;
    setInput("");
    setErr(null);
    setMsgs((m) => [...m, { id: mid(), role: "user", text: t }]);
    setBusy(true);
    try {
      applyReply(await api<AgentReply>("/agent/chat", { method: "POST", body: { message: t, ...(sessionId ? { session_id: sessionId } : {}) } }));
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 503 ? new ApiError(503, e.code, "에이전트를 지금 사용할 수 없어요. 잠시 후 다시 시도해 주세요.") : e);
    } finally {
      setBusy(false);
    }
  }

  async function decide(m: Msg, approve: boolean) {
    if (!m.pending || !sessionId) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api<AgentReply>("/agent/confirm", { method: "POST", body: { session_id: sessionId, action_id: m.pending.action_id, approve } });
      setMsgs((all) => all.map((x) => (x.id === m.id ? { ...x, resolved: true } : x)));
      applyReply(r);
      if (approve) void qc.invalidateQueries();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function openSession(id: string) {
    setListOpen(false);
    setErr(null);
    try {
      const rows = await api<StoredMsg[]>(`/agent/sessions/${id}/messages`);
      setSessionId(id);
      setMsgs(rows.map((r) => ({ id: `s${r.id}`, role: r.role === "USER" ? "user" : "agent", text: r.content, resolved: true })));
    } catch (e) {
      setErr(e);
    }
  }
  async function removeSession(id: string) {
    if (!confirm("이 대화를 삭제할까요?")) return;
    await api(`/agent/sessions/${id}`, { method: "DELETE" });
    if (id === sessionId) newChat();
    await qc.invalidateQueries({ queryKey: ["agent", "sessions"] });
  }
  function newChat() {
    setSessionId(null);
    setMsgs([]);
    setErr(null);
  }

  return (
    <div className="flex h-[calc(100dvh-64px)] flex-col">
      <PageHeader
        back={false}
        title="에이전트"
        right={
          <div className="flex gap-1 text-[13px] font-semibold text-brand">
            <button onClick={newChat} className="rounded-lg px-2 py-1 hover:bg-brand-soft">새 대화</button>
            <button onClick={() => setListOpen(true)} className="rounded-lg px-2 py-1 hover:bg-brand-soft">대화 목록</button>
          </div>
        }
      />
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {msgs.length === 0 && (
          <div className="space-y-4">
            <div className="rounded-2xl bg-brand-soft p-4 text-[14px]">
              <p className="font-semibold text-brand-dark">무엇을 도와드릴까요?</p>
              <p className="mt-1 text-[13px] text-sub">계좌·거래·카드·소비를 물어보거나 예산을 설정할 수 있어요. 이체처럼 PIN이 필요한 일은 해당 화면으로 안내해 드려요. 채팅에는 PIN·비밀번호를 입력하지 마세요.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="rounded-full border border-line bg-surface px-3 py-2 text-[13px] hover:border-brand">{s}</button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cx("max-w-[85%] space-y-2", m.role === "user" && "text-right")}>
              <p className={cx("inline-block whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-left text-[14px] leading-relaxed", m.role === "user" ? "bg-brand text-white" : "border border-line bg-surface")}>{m.text}</p>
              {m.notice && <p className="rounded-xl bg-warn-soft px-3 py-2 text-left text-[12px] text-warn">{m.notice}</p>}
              {m.pending && (
                <div className="rounded-2xl border border-brand bg-surface p-3 text-left">
                  <p className="text-[12px] font-semibold text-brand">확인이 필요해요</p>
                  <p className="my-1 text-[14px]">{m.pending.summary}</p>
                  {m.resolved ? <p className="text-[12px] text-sub">처리됨</p> : (
                    <div className="mt-2 flex gap-2">
                      <Button className="!h-10 flex-1" disabled={busy} onClick={() => decide(m, true)}>승인</Button>
                      <Button variant="ghost" className="!h-10 flex-1" disabled={busy} onClick={() => decide(m, false)}>취소</Button>
                    </div>
                  )}
                </div>
              )}
              {m.links && m.links.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {m.links.map((l) => (
                    <Link key={l.route} href={l.route} className="rounded-full bg-brand-soft px-3 py-1.5 text-[13px] font-semibold text-brand-dark hover:bg-[#dcefe4]">{l.label} ›</Link>
                  ))}
                </div>
              )}
              {m.sources && m.sources.length > 0 && (
                <p className="text-left text-[11px] text-sub">출처: {m.sources.map((s) => s.title).join(", ")}</p>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="text-[13px] text-sub">답변을 만드는 중…</p>}
        <ErrorBox error={err} />
        <div ref={endRef} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); void send(input); }} className="flex gap-2 border-t border-line bg-surface p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={500}
          placeholder="메시지를 입력하세요"
          aria-label="메시지"
          className="h-11 min-w-0 flex-1 rounded-full border border-line bg-bg px-4 text-[14px] outline-none focus:border-brand"
        />
        <Button type="submit" disabled={busy || !input.trim()} className="!h-11 !rounded-full">보내기</Button>
      </form>

      <Sheet open={listOpen} onClose={() => setListOpen(false)} title="대화 목록">
        {sessions.isPending ? <p className="text-sm text-sub">불러오는 중…</p> : !sessions.data?.length ? <p className="text-sm text-sub">저장된 대화가 없어요. 대화는 30일 동안 보관돼요.</p> : (
          <ul className="divide-y divide-line">
            {sessions.data.map((s) => (
              <li key={s.session_id} className="flex items-center justify-between gap-2 py-3">
                <button className="min-w-0 flex-1 text-left" onClick={() => openSession(s.session_id)}>
                  <p className="truncate text-[14px] font-medium">{s.title}</p>
                  <p className="text-[11px] text-sub">{fmtDateTime(s.last_at)}</p>
                </button>
                <button onClick={() => removeSession(s.session_id)} className="text-[12px] text-sub hover:text-danger">삭제</button>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
    </div>
  );
}
