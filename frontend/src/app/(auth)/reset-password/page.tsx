"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, DigitInput, ErrorBox, Field, Input, PageHeader, useToast } from "@/components/ui";

export default function ResetPasswordPage() {
  const router = useRouter();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [cool, setCool] = useState(0);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (cool <= 0) return;
    const t = setTimeout(() => setCool(cool - 1), 1000);
    return () => clearTimeout(t);
  }, [cool]);

  async function send() {
    setErr(null);
    try {
      await api("/auth/email-codes", { method: "POST", body: { email, purpose: "RESET_PW" } });
      setSent(true);
      setCool(60);
      toast("가입된 이메일이면 인증번호를 보냈어요");
    } catch (e) {
      setErr(e);
    }
  }
  const pwOk = /^(?=.*[A-Za-z])(?=.*\d)\S{8,64}$/.test(pw);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/password-reset", { method: "POST", body: { email, code, new_password: pw } });
      toast("비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요");
      router.replace("/login");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="비밀번호 재설정" back="/login" />
      <form onSubmit={submit} className="space-y-4 p-4">
        <Field label="가입한 이메일">
          <div className="flex gap-2">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value.trim())} autoComplete="email" />
            <Button type="button" variant="soft" className="shrink-0 px-3 text-[13px]" disabled={!email.includes("@") || cool > 0} onClick={send}>
              {cool > 0 ? `${cool}초` : sent ? "재전송" : "인증번호"}
            </Button>
          </div>
        </Field>
        {sent && (
          <>
            <Field label="인증번호" hint="6자리, 5분 안에 입력. 5회 틀리면 다시 받아야 해요">
              <DigitInput value={code} onChange={setCode} length={6} />
            </Field>
            <Field label="새 비밀번호" hint="공백 없이 영문+숫자 포함 8~64자" error={pw && !pwOk ? "형식이 올바르지 않습니다" : null}>
              <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
            </Field>
            <Field label="새 비밀번호 확인" error={pw2 && pw !== pw2 ? "비밀번호가 일치하지 않습니다" : null}>
              <Input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" />
            </Field>
          </>
        )}
        <ErrorBox error={err} />
        {sent && <Button type="submit" block loading={busy} disabled={code.length !== 6 || !pwOk || pw !== pw2}>비밀번호 변경</Button>}
      </form>
    </>
  );
}
