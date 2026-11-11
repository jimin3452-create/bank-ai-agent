"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type User } from "@/lib/api";
import { Button, DigitInput, ErrorBox, Field, Input } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"pw" | "pin">("pw");
  const [loginId, setLoginId] = useState("");
  const [secret, setSecret] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = mode === "pw" ? { login_id: loginId, password: secret } : { login_id: loginId, pin: secret };
      const r = await api<{ user: User }>(mode === "pw" ? "/auth/login" : "/auth/login-pin", { method: "POST", body });
      qc.setQueryData(["me"], r.user);
      router.replace("/home");
    } catch (e) {
      setErr(e);
      setSecret("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col justify-center px-6 py-10">
      <div className="mb-8">
        <p className="text-sm font-semibold text-brand">가상은행</p>
        <h1 className="mt-1 text-2xl font-bold">안녕하세요,<br />로그인해 주세요</h1>
      </div>
      <div className="mb-4 grid grid-cols-2 rounded-xl bg-brand-soft p-1 text-sm font-semibold">
        {(["pw", "pin"] as const).map((m) => (
          <button key={m} type="button" onClick={() => { setMode(m); setSecret(""); setErr(null); }} className={`h-9 rounded-lg ${mode === m ? "bg-surface text-brand-dark shadow-sm" : "text-sub"}`}>
            {m === "pw" ? "비밀번호" : "간편 PIN"}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="space-y-4">
        <Field label="아이디">
          <Input value={loginId} onChange={(e) => setLoginId(e.target.value.trim())} autoComplete="username" autoCapitalize="none" placeholder="아이디" />
        </Field>
        {mode === "pw" ? (
          <Field label="비밀번호">
            <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="current-password" placeholder="비밀번호" />
          </Field>
        ) : (
          <Field label="PIN">
            <DigitInput value={secret} onChange={setSecret} length={6} secret />
          </Field>
        )}
        <ErrorBox error={err} />
        <Button type="submit" block loading={busy} disabled={!loginId || (mode === "pw" ? !secret : secret.length !== 6)}>로그인</Button>
      </form>
      <div className="mt-6 flex justify-center gap-4 text-sm text-sub">
        <Link href="/signup" className="hover:text-brand">회원가입</Link>
        <span>·</span>
        <Link href="/reset-password" className="hover:text-brand">비밀번호 재설정</Link>
      </div>
    </main>
  );
}
