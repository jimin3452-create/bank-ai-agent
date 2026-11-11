"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, fmtDateTime, type User } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";
import { Badge, Button, Card, DigitInput, ErrorBox, Field, Input, PageHeader, PinSheet, Row, Sheet, Spinner, useToast } from "@/components/ui";

type History = { id: number; ip: string | null; user_agent: string | null; success: boolean; created_at: string };
type WithdrawCheck = { allowed: boolean; reasons: { code: string; message: string }[] };
type Panel = null | "profile" | "pin" | "withdraw" | "history";

function ProfileSheet({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [phone, setPhone] = useState(user.phone_num);
  const [birth, setBirth] = useState(user.birth ?? "");
  const [email, setEmail] = useState(user.email);
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const emailChanged = email.trim().toLowerCase() !== user.email.toLowerCase();

  async function sendCode() {
    setErr(null);
    try {
      await api("/me/email-code", { method: "POST", body: { email: email.trim() } });
      setSent(true);
      toast("새 이메일로 인증번호를 보냈어요");
    } catch (e) {
      setErr(e);
    }
  }
  async function save() {
    const body: Record<string, string> = { pin };
    if (phone !== user.phone_num) body.phone_num = phone;
    if (birth && birth !== (user.birth ?? "")) body.birth = birth;
    if (emailChanged) { body.email = email.trim(); body.email_code = code; }
    if (Object.keys(body).length === 1) { setErr(new Error("변경한 항목이 없어요")); return; }
    setBusy(true);
    setErr(null);
    try {
      const u = await api<User>("/me", { method: "PATCH", body });
      qc.setQueryData(["me"], u);
      toast("정보를 변경했어요");
      onClose();
    } catch (e) {
      setErr(e);
      setPin("");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <p className="text-[12px] text-sub">이름은 변경할 수 없어요. 변경하려면 PIN 확인이 필요해요.</p>
      <Field label="휴대폰 번호"><Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="010-1234-5678" inputMode="tel" /></Field>
      <Field label="생년월일"><Input type="date" value={birth} onChange={(e) => setBirth(e.target.value)} /></Field>
      <Field label="이메일"><Input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setSent(false); }} /></Field>
      {emailChanged && (
        <div className="space-y-2">
          <Button variant="soft" block type="button" onClick={sendCode}>{sent ? "인증번호 다시 받기" : "새 이메일로 인증번호 받기"}</Button>
          {sent && <Field label="인증번호" hint="6자리 · 5분 이내 입력"><DigitInput value={code} onChange={setCode} length={6} /></Field>}
        </div>
      )}
      <Field label="PIN 확인"><DigitInput value={pin} onChange={setPin} length={6} secret placeholder="PIN 6자리" /></Field>
      <ErrorBox error={err} />
      <Button block loading={busy} disabled={pin.length !== 6 || (emailChanged && code.length !== 6)} onClick={save}>저장</Button>
    </div>
  );
}

function PinChangeSheet({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = again.length === 6 && next !== again;
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await api("/me/pin", { method: "PUT", body: { current_pin: cur, new_pin: next } });
      toast("PIN을 변경했어요");
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <Field label="현재 PIN"><DigitInput value={cur} onChange={setCur} length={6} secret /></Field>
      <Field label="새 PIN"><DigitInput value={next} onChange={setNext} length={6} secret /></Field>
      <Field label="새 PIN 확인" error={mismatch ? "새 PIN이 일치하지 않아요" : null}><DigitInput value={again} onChange={setAgain} length={6} secret /></Field>
      <ErrorBox error={err} />
      <Button block loading={busy} disabled={cur.length !== 6 || next.length !== 6 || next !== again} onClick={go}>PIN 변경</Button>
    </div>
  );
}

function MeInner() {
  const router = useRouter();
  const sp = useSearchParams();
  const qc = useQueryClient();
  const me = useMe();
  const logout = useLogout();
  const focus = sp.get("focus");
  const [panel, setPanel] = useState<Panel>(() => (focus === "profile" ? "profile" : focus === "password" ? "pin" : focus === "withdraw" ? "withdraw" : null));
  const [pinForWithdraw, setPinForWithdraw] = useState(false);

  const history = useQuery({ queryKey: ["me", "history"], queryFn: () => api<History[]>("/me/login-histories"), enabled: panel === "history" });
  const check = useQuery({ queryKey: ["me", "withdraw-check"], queryFn: () => api<WithdrawCheck>("/me/withdraw-check"), enabled: panel === "withdraw" });

  // 에이전트 링크의 ?focus= 로 해당 항목을 바로 연다(logout 은 바로 실행)
  useEffect(() => {
    if (focus === "logout") void logout();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  if (!me.data) return <Spinner />;
  const u = me.data;
  const open = (p: Panel) => () => { setPanel(p); router.replace("/me"); };

  return (
    <>
      <PageHeader back={false} title="내 정보" />
      <main className="space-y-4 p-4">
        <Card>
          <p className="text-lg font-bold">{u.user_name}</p>
          <p className="text-[13px] text-sub">@{u.login_id}</p>
          <dl className="mt-3 space-y-1.5 text-[13px]">
            <div className="flex justify-between"><dt className="text-sub">휴대폰</dt><dd>{u.phone_num}</dd></div>
            <div className="flex justify-between"><dt className="text-sub">이메일</dt><dd>{u.email}</dd></div>
            <div className="flex justify-between"><dt className="text-sub">생년월일</dt><dd>{u.birth ?? "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-sub">가입일</dt><dd>{u.created_at.slice(0, 10)}</dd></div>
          </dl>
        </Card>

        <Card className="divide-y divide-line py-1">
          <Row onClick={open("profile")} left={<span className="text-[14px] font-medium">정보 변경</span>} right={<span className="text-sub">›</span>} />
          <Row onClick={open("pin")} left={<span className="text-[14px] font-medium">PIN 변경</span>} right={<span className="text-sub">›</span>} />
          <Row onClick={open("history")} left={<span className="text-[14px] font-medium">접속 기록</span>} right={<span className="text-sub">›</span>} />
          <Row onClick={() => void logout()} left={<span className="text-[14px] font-medium">로그아웃</span>} right={<span className="text-sub">›</span>} />
          <Row onClick={open("withdraw")} left={<span className="text-[14px] font-medium text-danger">회원 탈퇴</span>} right={<span className="text-sub">›</span>} />
        </Card>
        <p className="text-center text-[11px] text-sub">10분 동안 사용하지 않으면 자동으로 로그아웃돼요.</p>
      </main>

      <Sheet open={panel === "profile"} onClose={() => setPanel(null)} title="정보 변경">
        <ProfileSheet user={u} onClose={() => setPanel(null)} />
      </Sheet>
      <Sheet open={panel === "pin"} onClose={() => setPanel(null)} title="PIN 변경">
        <PinChangeSheet onClose={() => setPanel(null)} />
      </Sheet>
      <Sheet open={panel === "history"} onClose={() => setPanel(null)} title="접속 기록">
        {history.isPending ? <Spinner /> : (
          <ul className="divide-y divide-line">
            {history.data?.map((h) => (
              <li key={h.id} className="py-2.5 text-[13px]">
                <div className="flex justify-between"><span>{fmtDateTime(h.created_at)}</span><Badge tone={h.success ? "green" : "red"}>{h.success ? "성공" : "실패"}</Badge></div>
                <p className="truncate text-[11px] text-sub">{h.ip} · {h.user_agent}</p>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
      <Sheet open={panel === "withdraw"} onClose={() => setPanel(null)} title="회원 탈퇴">
        {check.isPending ? <Spinner /> : check.error ? <ErrorBox error={check.error} /> : check.data.allowed ? (
          <div className="space-y-3">
            <p className="text-sm">탈퇴하면 계정을 되돌릴 수 없어요. 계속할까요?</p>
            <Button variant="danger" block onClick={() => setPinForWithdraw(true)}>PIN 입력하고 탈퇴</Button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm font-semibold">아래 사유를 해결한 뒤 탈퇴할 수 있어요.</p>
            <ul className="space-y-2">
              {check.data.reasons.map((r) => <li key={r.code} className="rounded-xl bg-danger-soft px-3 py-2.5 text-[13px] text-danger">{r.message}</li>)}
            </ul>
          </div>
        )}
      </Sheet>
      <PinSheet
        open={pinForWithdraw}
        onClose={() => setPinForWithdraw(false)}
        title="탈퇴 확인"
        description="PIN을 입력하면 즉시 탈퇴 처리돼요."
        onSubmit={async (pin) => {
          await api("/me/withdraw", { method: "POST", body: { pin } });
          qc.clear();
          router.replace("/login");
        }}
      />
    </>
  );
}

export default function MePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <MeInner />
    </Suspense>
  );
}
