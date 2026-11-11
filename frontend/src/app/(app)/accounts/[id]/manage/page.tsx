"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, won, type AccountDetail } from "@/lib/api";
import { Button, Card, DigitInput, ErrorBox, Field, Input, MoneyInput, PageHeader, PinSheet, Spinner, cx, useToast } from "@/components/ui";

type Limits = { daily_limit: number; month_limit: number; used_today: number; used_month: number; remaining_today: number; daily_limit_range: [number, number]; month_limit_range: [number, number] };

function Section({ id, title, focus, children }: { id: string; title: string; focus: boolean; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focus) ref.current?.scrollIntoView({ block: "center" });
  }, [focus]);
  return (
    <div ref={ref} id={id}>
      <Card className={cx("space-y-3", focus && "ring-2 ring-brand")}>
        <h2 className="text-[15px] font-bold">{title}</h2>
        {children}
      </Card>
    </div>
  );
}

function Inner() {
  const { id } = useParams<{ id: string }>();
  const focus = useSearchParams().get("focus") ?? "";
  const qc = useQueryClient();
  const toast = useToast();
  const acc = useQuery({ queryKey: ["account", id], queryFn: () => api<AccountDetail>(`/accounts/${id}`) });
  const limits = useQuery({ queryKey: ["limits", id], queryFn: () => api<Limits>(`/accounts/${id}/limits`) });
  const a = acc.data;

  const refresh = () => Promise.all(["account", "accounts", "limits"].map((k) => qc.invalidateQueries({ queryKey: [k] })));

  // 별칭
  const [nick, setNick] = useState<string | null>(null);
  const [nickErr, setNickErr] = useState<unknown>(null);
  async function saveNick() {
    setNickErr(null);
    try {
      await api(`/accounts/${id}/nickname`, { method: "PUT", body: { nickname: nick ?? "" } });
      await refresh();
      setNick(null);
      toast("별칭을 바꿨어요");
    } catch (e) {
      setNickErr(e);
    }
  }
  async function toggleFav() {
    await api(`/accounts/${id}/favorite`, { method: "PUT", body: { is_favorite: !a?.is_favorite } });
    await refresh();
  }

  // 한도
  const [daily, setDaily] = useState<string | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  const [pinOpen, setPinOpen] = useState(false);
  const dVal = daily ?? String(limits.data?.daily_limit ?? "");
  const mVal = month ?? String(limits.data?.month_limit ?? "");
  const L = limits.data;
  const limitMsg = !L ? null
    : Number(dVal) < L.daily_limit_range[0] || Number(dVal) > L.daily_limit_range[1] ? `1일 한도는 ${won(L.daily_limit_range[0])}~${won(L.daily_limit_range[1])}`
    : Number(mVal) < L.month_limit_range[0] || Number(mVal) > L.month_limit_range[1] ? `1달 한도는 ${won(L.month_limit_range[0])}~${won(L.month_limit_range[1])}`
    : Number(dVal) > Number(mVal) ? "1일 한도는 1달 한도보다 클 수 없어요" : null;

  // 통장 비밀번호 확인 / 거래중지 해제
  const [apw, setApw] = useState("");
  const [apwErr, setApwErr] = useState<unknown>(null);
  const [apwOk, setApwOk] = useState(false);
  async function verifyPw() {
    setApwErr(null);
    setApwOk(false);
    try {
      await api(`/accounts/${id}/verify-password`, { method: "POST", body: { account_password: apw } });
      setApwOk(true);
    } catch (e) {
      setApwErr(e);
      await refresh(); // 5회 실패로 거래중지가 되었을 수 있다
    }
    setApw("");
  }
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [unlockErr, setUnlockErr] = useState<unknown>(null);
  async function sendCode() {
    setUnlockErr(null);
    try {
      await api(`/accounts/${id}/unlock/email-code`, { method: "POST" });
      setCodeSent(true);
      toast("가입한 이메일로 인증번호를 보냈어요");
    } catch (e) {
      setUnlockErr(e);
    }
  }
  async function unlock() {
    setUnlockErr(null);
    try {
      await api(`/accounts/${id}/unlock`, { method: "POST", body: { code } });
      await refresh();
      setCodeSent(false);
      setCode("");
      toast("거래중지를 해제했어요");
    } catch (e) {
      setUnlockErr(e);
    }
  }

  if (acc.isPending) return <><PageHeader title="계좌 관리" /><Spinner /></>;
  if (!a) return <><PageHeader title="계좌 관리" /><div className="p-4"><ErrorBox error={acc.error} /></div></>;
  const suspended = a.status === "SUSPENDED";

  return (
    <>
      <PageHeader title="계좌 관리" back={`/accounts/${id}`} />
      <main className="space-y-4 p-4 pb-10">
        <Card>
          <p className="font-semibold">{a.nickname ?? a.product_name}</p>
          <p className="tabular text-[13px] text-sub">{a.account_num} · {won(a.balance)}</p>
        </Card>

        <Section id="basic" title="별칭 · 즐겨찾기" focus={false}>
          <Field label="별칭" error={nickErr ? (nickErr as Error).message : null}>
            <div className="flex gap-2">
              <Input value={nick ?? a.nickname ?? ""} maxLength={50} onChange={(e) => setNick(e.target.value)} />
              <Button className="shrink-0 px-4" variant="soft" disabled={nick === null || !nick.trim()} onClick={saveNick}>저장</Button>
            </div>
          </Field>
          <label className="flex items-center justify-between text-[14px]">
            즐겨찾기 계좌
            <input type="checkbox" className="h-5 w-5" checked={a.is_favorite} onChange={toggleFav} />
          </label>
        </Section>

        <Section id="limit" title="이체한도" focus={focus === "limit"}>
          {L && (
            <p className="text-[12px] text-sub">오늘 사용 {won(L.used_today)} (남은 {won(L.remaining_today)}) · 이번 달 사용 {won(L.used_month)}</p>
          )}
          <Field label="1일 한도"><MoneyInput value={dVal} onChange={setDaily} /></Field>
          <Field label="1달 한도" hint={L ? `1일 ${won(L.daily_limit_range[0])}~${won(L.daily_limit_range[1])}, 1달 ${won(L.month_limit_range[0])}~${won(L.month_limit_range[1])}` : undefined} error={limitMsg}>
            <MoneyInput value={mVal} onChange={setMonth} />
          </Field>
          <Button block disabled={!L || !!limitMsg || (Number(dVal) === L.daily_limit && Number(mVal) === L.month_limit) || suspended} onClick={() => setPinOpen(true)}>한도 변경</Button>
        </Section>

        <Section id="password" title="통장 비밀번호 확인" focus={focus === "password"}>
          <Field label="통장 비밀번호" hint="5회 틀리면 거래가 중지돼요">
            <DigitInput value={apw} onChange={setApw} length={4} secret />
          </Field>
          {apwOk && <p className="text-[13px] font-medium text-brand">✓ 비밀번호가 맞아요</p>}
          <ErrorBox error={apwErr} />
          <Button block variant="soft" disabled={apw.length !== 4 || suspended} onClick={verifyPw}>확인</Button>
        </Section>

        {suspended && (
          <Section id="unlock" title="거래중지 해제" focus={focus === "unlock"}>
            <p className="text-[13px] text-sub">통장 비밀번호를 5회 틀려 거래가 중지되었어요. 가입한 이메일로 받은 인증번호로 본인확인하면 해제돼요.</p>
            {!codeSent ? (
              <Button block onClick={sendCode}>인증번호 받기</Button>
            ) : (
              <>
                <DigitInput value={code} onChange={setCode} length={6} placeholder="인증번호 6자리" />
                <Button block disabled={code.length !== 6} onClick={unlock}>해제하기</Button>
                <button type="button" onClick={sendCode} className="w-full text-center text-[12px] text-sub underline">인증번호 다시 받기</button>
              </>
            )}
            <ErrorBox error={unlockErr} />
          </Section>
        )}

        <Link href={`/accounts/${id}/close`} className="block rounded-xl border border-danger/40 py-3 text-center text-sm font-semibold text-danger">계좌 해지하기</Link>
      </main>

      <PinSheet open={pinOpen} onClose={() => setPinOpen(false)} title="이체한도 변경" description="PIN을 입력하면 한도가 바뀌어요."
        onSubmit={async (pin) => {
          await api(`/accounts/${id}/limits`, { method: "PUT", body: { daily_limit: Number(dVal), month_limit: Number(mVal), pin } });
          await refresh();
          setDaily(null);
          setMonth(null);
          toast("이체한도를 바꿨어요");
        }} />
    </>
  );
}

export default function ManagePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Inner />
    </Suspense>
  );
}
