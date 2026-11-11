"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, DigitInput, ErrorBox, Field, Input, PageHeader, useToast } from "@/components/ui";

type Term = { id: number; title: string; content: string; version: string; required: boolean };

export default function SignupPage() {
  const router = useRouter();
  const toast = useToast();
  const terms = useQuery({ queryKey: ["terms", "SIGNUP"], queryFn: () => api<Term[]>("/terms", { query: { category: "SIGNUP" } }) });

  const [f, setF] = useState({ login_id: "", password: "", password2: "", pin: "", pin2: "", user_name: "", phone_num: "", birth: "", email: "" });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  const [agreed, setAgreed] = useState<number[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [dup, setDup] = useState<{ login_id?: boolean }>({});

  // 이메일 인증
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [cool, setCool] = useState(0);
  const [mailErr, setMailErr] = useState<unknown>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (cool <= 0) return;
    const t = setTimeout(() => setCool(cool - 1), 1000);
    return () => clearTimeout(t);
  }, [cool]);

  async function checkLoginId() {
    if (!/^[a-z0-9_]{4,30}$/.test(f.login_id)) return setDup({});
    const r = await api<{ duplicate: boolean }>("/auth/check-duplicate", { query: { field: "login_id", value: f.login_id } }).catch(() => null);
    if (r) setDup({ login_id: r.duplicate });
  }
  async function sendCode() {
    setMailErr(null);
    try {
      await api("/auth/email-codes", { method: "POST", body: { email: f.email, purpose: "SIGNUP" } });
      setSent(true);
      setVerified(false);
      setCool(60);
      toast("인증번호를 보냈어요 (5분 안에 입력)");
    } catch (e) {
      setMailErr(e);
    }
  }
  async function verify() {
    setMailErr(null);
    try {
      await api("/auth/email-codes/verify", { method: "POST", body: { email: f.email, purpose: "SIGNUP", code } });
      setVerified(true);
    } catch (e) {
      setMailErr(e);
    }
  }

  const required = (terms.data ?? []).filter((t) => t.required).map((t) => t.id);
  const allRequired = required.every((id) => agreed.includes(id));
  const pwOk = /^(?=.*[A-Za-z])(?=.*\d)\S{8,64}$/.test(f.password);
  const ready =
    /^[a-z0-9_]{4,30}$/.test(f.login_id) && !dup.login_id && pwOk && f.password === f.password2 && f.pin.length === 6 && f.pin === f.pin2 &&
    f.user_name.trim() && /^01[016789]-\d{3,4}-\d{4}$/.test(f.phone_num) && verified && allRequired;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/signup", {
        method: "POST",
        body: { login_id: f.login_id, password: f.password, pin: f.pin, email: f.email, user_name: f.user_name.trim(), phone_num: f.phone_num, birth: f.birth || null, agreed_term_ids: agreed },
      });
      toast("가입이 완료되었어요. 로그인해 주세요");
      router.replace("/login");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="회원가입" back="/login" />
      <form onSubmit={submit} className="space-y-4 p-4 pb-10">
        <Field label="아이디" hint="영문 소문자·숫자·밑줄 4~30자" error={dup.login_id ? "이미 사용 중인 아이디입니다" : null}>
          <Input value={f.login_id} onChange={(e) => set("login_id")(e.target.value.trim())} onBlur={checkLoginId} autoCapitalize="none" autoComplete="username" />
        </Field>
        <Field label="비밀번호" hint="공백 없이 영문+숫자 포함 8~64자" error={f.password && !pwOk ? "형식이 올바르지 않습니다" : null}>
          <Input type="password" value={f.password} onChange={(e) => set("password")(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label="비밀번호 확인" error={f.password2 && f.password !== f.password2 ? "비밀번호가 일치하지 않습니다" : null}>
          <Input type="password" value={f.password2} onChange={(e) => set("password2")(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label="간편 PIN" hint="이체·카드 관리 때 쓰는 숫자 6자리">
          <DigitInput value={f.pin} onChange={set("pin")} length={6} secret />
        </Field>
        <Field label="PIN 확인" error={f.pin2 && f.pin !== f.pin2 ? "PIN이 일치하지 않습니다" : null}>
          <DigitInput value={f.pin2} onChange={set("pin2")} length={6} secret />
        </Field>
        <Field label="이름">
          <Input value={f.user_name} onChange={(e) => set("user_name")(e.target.value)} maxLength={50} />
        </Field>
        <Field label="휴대폰 번호" hint="예: 010-1234-5678">
          <Input value={f.phone_num} inputMode="tel" onChange={(e) => set("phone_num")(e.target.value.replace(/[^\d-]/g, ""))} placeholder="010-0000-0000" />
        </Field>
        <Field label="생년월일 (선택)">
          <Input type="date" value={f.birth} max={new Date().toISOString().slice(0, 10)} onChange={(e) => set("birth")(e.target.value)} />
        </Field>

        <div className="space-y-2">
          <Field label="이메일">
            <div className="flex gap-2">
              <Input type="email" value={f.email} disabled={verified} onChange={(e) => set("email")(e.target.value.trim())} autoComplete="email" />
              <Button type="button" variant="soft" className="shrink-0 px-3 text-[13px]" disabled={!f.email.includes("@") || cool > 0 || verified} onClick={sendCode}>
                {cool > 0 ? `${cool}초` : sent ? "재전송" : "인증번호"}
              </Button>
            </div>
          </Field>
          {sent && !verified && (
            <div className="flex gap-2">
              <DigitInput value={code} onChange={setCode} length={6} placeholder="인증번호 6자리" />
              <Button type="button" className="shrink-0 px-4" disabled={code.length !== 6} onClick={verify}>확인</Button>
            </div>
          )}
          {verified && <p className="text-[13px] font-medium text-brand">✓ 이메일 인증이 완료되었어요</p>}
          <ErrorBox error={mailErr} />
          <p className="text-[12px] text-sub">개발 환경에서는 인증번호 메일을 <a className="underline" href="http://localhost:8025" target="_blank" rel="noreferrer">Mailpit</a>에서 확인하세요.</p>
        </div>

        <Card className="space-y-2">
          <label className="flex items-center gap-2 text-[14px] font-semibold">
            <input type="checkbox" checked={!!terms.data && agreed.length === terms.data.length} onChange={(e) => setAgreed(e.target.checked ? (terms.data ?? []).map((t) => t.id) : [])} />
            전체 동의
          </label>
          {terms.data?.map((t) => (
            <div key={t.id} className="border-t border-line pt-2">
              <div className="flex items-center justify-between gap-2">
                <label className="flex items-center gap-2 text-[13px]">
                  <input type="checkbox" checked={agreed.includes(t.id)} onChange={(e) => setAgreed((a) => (e.target.checked ? [...a, t.id] : a.filter((x) => x !== t.id)))} />
                  [{t.required ? "필수" : "선택"}] {t.title}
                </label>
                <button type="button" className="text-[12px] text-sub underline" onClick={() => setOpen(open === t.id ? null : t.id)}>{open === t.id ? "접기" : "보기"}</button>
              </div>
              {open === t.id && <p className="mt-2 max-h-40 overflow-y-auto rounded-lg bg-bg p-3 text-[12px] leading-relaxed text-sub">{t.content}</p>}
            </div>
          ))}
        </Card>

        <ErrorBox error={err} />
        <Button type="submit" block loading={busy} disabled={!ready}>가입하기</Button>
        <p className="text-center text-sm text-sub">이미 회원이세요? <Link href="/login" className="text-brand">로그인</Link></p>
      </form>
    </>
  );
}
