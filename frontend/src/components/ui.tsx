"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { ApiError } from "@/lib/api";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---------- 버튼 ----------
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "soft"; block?: boolean; loading?: boolean };
export function Button({ variant = "primary", block, loading, className, children, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-brand text-white hover:bg-brand-dark",
    soft: "bg-brand-soft text-brand-dark hover:bg-[#dcefe4]",
    ghost: "border border-line bg-surface text-ink hover:bg-bg",
    danger: "bg-danger text-white hover:opacity-90",
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx("h-12 rounded-xl px-4 text-[15px] font-semibold transition", v, block && "w-full", className)}
    >
      {loading ? "처리 중…" : children}
    </button>
  );
}

// ---------- 입력 ----------
export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-sub">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-[12px] text-danger">{error}</span> : hint ? <span className="mt-1 block text-[12px] text-sub">{hint}</span> : null}
    </label>
  );
}
export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      className={cx("h-12 w-full rounded-xl border border-line bg-surface px-3.5 text-[15px] outline-none placeholder:text-[#a3b0aa] focus:border-brand", className)}
    />
  );
}
export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={cx("h-12 w-full rounded-xl border border-line bg-surface px-3 text-[15px] outline-none focus:border-brand", className)}>
      {children}
    </select>
  );
}
/** 숫자만 받는 입력(PIN·통장 비밀번호·인증번호). 마스킹이 필요하면 secret. */
export function DigitInput({ value, onChange, length, secret, placeholder, autoFocus }: { value: string; onChange: (v: string) => void; length: number; secret?: boolean; placeholder?: string; autoFocus?: boolean }) {
  return (
    <Input
      value={value}
      inputMode="numeric"
      type={secret ? "password" : "text"}
      autoComplete="off"
      maxLength={length}
      autoFocus={autoFocus}
      placeholder={placeholder ?? `숫자 ${length}자리`}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, length))}
      className="tracking-[0.3em]"
    />
  );
}
export function MoneyInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const shown = value ? Number(value).toLocaleString("ko-KR") : "";
  return <Input value={shown} inputMode="numeric" placeholder={placeholder ?? "금액(원)"} onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 12))} />;
}

// ---------- 레이아웃 조각 ----------
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx("rounded-2xl border border-line bg-surface p-4", className)}>{children}</section>;
}
export function PageHeader({ title, back = true, right }: { title: string; back?: boolean | string; right?: ReactNode }) {
  const router = useRouter();
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line bg-surface/95 px-3 backdrop-blur">
      {back ? (
        <button aria-label="뒤로" onClick={() => (typeof back === "string" ? router.push(back) : router.back())} className="grid h-10 w-10 place-items-center rounded-full text-xl hover:bg-bg">
          ‹
        </button>
      ) : (
        <span className="w-2" />
      )}
      <h1 className="flex-1 truncate text-[17px] font-bold">{title}</h1>
      {right}
    </header>
  );
}
export function Spinner({ label = "불러오는 중…" }: { label?: string }) {
  return <p className="py-10 text-center text-sm text-sub">{label}</p>;
}
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? error.message : "알 수 없는 오류가 발생했습니다.";
  return <p role="alert" className="rounded-xl bg-danger-soft px-3.5 py-3 text-[13px] text-danger">{msg}</p>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-10 text-center text-sm text-sub">{children}</p>;
}
export function Badge({ tone = "gray", children }: { tone?: "gray" | "green" | "red" | "amber"; children: ReactNode }) {
  const t = { gray: "bg-bg text-sub", green: "bg-brand-soft text-brand-dark", red: "bg-danger-soft text-danger", amber: "bg-warn-soft text-warn" }[tone];
  return <span className={cx("inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", t)}>{children}</span>;
}
export function Row({ left, right, onClick }: { left: ReactNode; right?: ReactNode; onClick?: () => void }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag onClick={onClick} className="flex w-full items-center justify-between gap-3 py-3 text-left">
      <div className="min-w-0">{left}</div>
      {right !== undefined && <div className="shrink-0 text-right">{right}</div>}
    </Tag>
  );
}

// ---------- 모달 / PIN ----------
export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby={id} onClick={(e) => e.stopPropagation()} className="max-h-[88dvh] w-full max-w-[430px] overflow-y-auto rounded-t-3xl bg-surface p-5 pb-8">
        <h2 id={id} className="mb-4 text-lg font-bold">{title}</h2>
        {children}
      </div>
    </div>
  );
}
/** PIN 입력 시트. onSubmit 이 던지는 오류는 시트 안에 보여 준다. 성공하면 닫힌다. */
export function PinSheet({ open, onClose, title = "PIN 확인", description, onSubmit }: { open: boolean; onClose: () => void; title?: string; description?: string; onSubmit: (pin: string) => Promise<unknown> }) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <PinForm onClose={onClose} description={description} onSubmit={onSubmit} />
    </Sheet>
  );
}
function PinForm({ onClose, description, onSubmit }: { onClose: () => void; description?: string; onSubmit: (pin: string) => Promise<unknown> }) {
  // 시트가 닫히면 이 컴포넌트가 사라지므로 입력값·오류는 자동으로 초기화된다.
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await onSubmit(pin);
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
      {description && <p className="text-sm text-sub">{description}</p>}
      <DigitInput value={pin} onChange={setPin} length={6} secret autoFocus placeholder="PIN 6자리" />
      <ErrorBox error={err} />
      <Button block loading={busy} disabled={pin.length !== 6} onClick={go}>확인</Button>
    </div>
  );
}

// ---------- 토스트 ----------
const ToastCtx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(null), 2600);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <div role="status" className="fixed inset-x-0 bottom-24 z-[60] mx-auto w-fit max-w-[380px] rounded-full bg-brand-dark px-5 py-2.5 text-sm text-white shadow-lg">
          {msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}
