"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, type AccountDetail } from "@/lib/api";
import { Badge, Button, Card, DigitInput, ErrorBox, Field, Input, PageHeader, Select, Spinner, useToast } from "@/components/ui";

type Product = { id: number; product_name: string; interest_rate: number; description: string; product_type: string; join_condition: string; rate_condition: string };
type Term = { id: number; title: string; content: string; required: boolean };

const PURPOSES = [["SALARY", "급여·생활비"], ["SAVING", "저축·투자"], ["LIVING", "공과금·생활"], ["BUSINESS", "사업"], ["OTHER", "기타"]];
const INCOMES = [["SALARY_INCOME", "근로소득"], ["BUSINESS_INCOME", "사업소득"], ["PENSION", "연금"], ["ALLOWANCE", "용돈"], ["OTHER", "기타"]];

function Inner() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const sp = useSearchParams();
  const [productId, setProductId] = useState<number | null>(sp.get("product_id") ? Number(sp.get("product_id")) : null);

  const products = useQuery({ queryKey: ["products"], queryFn: () => api<Product[]>("/products") });
  const elig = useQuery({
    queryKey: ["eligibility", productId],
    queryFn: () => api<{ eligible: boolean; reasons: { code: string; message: string }[] }>(`/products/${productId}/eligibility`),
    enabled: productId !== null,
  });
  const terms = useQuery({ queryKey: ["terms", "ACCOUNT_OPEN"], queryFn: () => api<Term[]>("/terms", { query: { category: "ACCOUNT_OPEN" } }) });

  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [purpose, setPurpose] = useState("SALARY");
  const [income, setIncome] = useState("SALARY_INCOME");
  const [nick, setNick] = useState("");
  const [agreed, setAgreed] = useState<number[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<AccountDetail | null>(null);

  const product = products.data?.find((p) => p.id === productId);
  const weak = ["0000", "1111", "1234", "4321"].includes(pw);
  const requiredOk = (terms.data ?? []).filter((t) => t.required).every((t) => agreed.includes(t.id));
  const ready = !!product && elig.data?.eligible && pw.length === 4 && pw === pw2 && requiredOk;

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const a = await api<AccountDetail>("/accounts", {
        method: "POST",
        body: { product_id: productId, account_password: pw, account_password_confirm: pw2, purpose, income_source: income, nickname: nick.trim() || null, agreed_term_ids: agreed },
      });
      await qc.invalidateQueries({ queryKey: ["accounts"] });
      toast("계좌가 개설되었어요");
      setDone(a);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <>
        <PageHeader title="계좌 개설 완료" back={false} />
        <main className="space-y-4 p-4">
          <Card className="space-y-1 text-center">
            <p className="text-3xl">🎉</p>
            <p className="font-bold">{done.nickname ?? done.product_name}</p>
            <p className="tabular text-lg">{done.account_num}</p>
            <p className="text-[13px] text-sub">{done.product_name} · 연 {done.interest_rate}%</p>
          </Card>
          <Button block onClick={() => router.replace(`/accounts/${done.id}`)}>계좌 보기</Button>
          <Button block variant="ghost" onClick={() => router.replace("/home")}>홈으로</Button>
        </main>
      </>
    );

  return (
    <>
      <PageHeader title="계좌 개설" back="/home" />
      <main className="space-y-4 p-4 pb-10">
        <section>
          <h2 className="mb-2 text-[15px] font-bold">1. 상품 선택</h2>
          {products.isPending ? <Spinner /> : products.error ? <ErrorBox error={products.error} /> : (
            <div className="space-y-2">
              {products.data.map((p) => (
                <button key={p.id} onClick={() => setProductId(p.id)} className={`block w-full rounded-2xl border p-4 text-left ${p.id === productId ? "border-brand bg-brand-soft" : "border-line bg-surface"}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-semibold">{p.product_name}</span>
                    <Badge tone="green">연 {p.interest_rate}%</Badge>
                  </div>
                  <p className="mt-1 text-[13px] text-sub">{p.description}</p>
                  <p className="mt-1 text-[12px] text-sub">가입 조건: {p.join_condition}</p>
                </button>
              ))}
            </div>
          )}
          {product && <p className="mt-2 text-[12px] text-sub">우대금리: {product.rate_condition}</p>}
          {elig.data && !elig.data.eligible && (
            <div role="alert" className="mt-2 space-y-1 rounded-xl bg-danger-soft px-3.5 py-3 text-[13px] text-danger">
              <p className="font-semibold">이 상품은 지금 개설할 수 없어요</p>
              {elig.data.reasons.map((r) => <p key={r.code}>· {r.message}</p>)}
            </div>
          )}
        </section>

        {product && elig.data?.eligible && (
          <section className="space-y-4">
            <h2 className="text-[15px] font-bold">2. 정보 입력</h2>
            <Field label="통장 비밀번호" hint="숫자 4자리. 5회 틀리면 거래가 중지돼요" error={weak ? "너무 쉬운 번호예요. 다른 번호를 권장해요" : null}>
              <DigitInput value={pw} onChange={setPw} length={4} secret />
            </Field>
            <Field label="통장 비밀번호 확인" error={pw2 && pw !== pw2 ? "비밀번호가 일치하지 않습니다" : null}>
              <DigitInput value={pw2} onChange={setPw2} length={4} secret />
            </Field>
            <Field label="거래 목적">
              <Select value={purpose} onChange={(e) => setPurpose(e.target.value)}>{PURPOSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            </Field>
            <Field label="소득 원천">
              <Select value={income} onChange={(e) => setIncome(e.target.value)}>{INCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            </Field>
            <Field label="계좌 별칭 (선택)">
              <Input value={nick} maxLength={50} onChange={(e) => setNick(e.target.value)} placeholder="예: 월급통장" />
            </Field>

            <h2 className="text-[15px] font-bold">3. 약관 동의</h2>
            <Card className="space-y-2">
              {terms.data?.map((t) => (
                <div key={t.id} className="border-b border-line pb-2 last:border-0 last:pb-0">
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
            <p className="text-[12px] text-sub">한 사람이 가질 수 있는 계좌는 최대 5개예요.</p>
            <ErrorBox error={err} />
            <Button block loading={busy} disabled={!ready} onClick={submit}>계좌 개설하기</Button>
          </section>
        )}
      </main>
    </>
  );
}

export default function NewAccountPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Inner />
    </Suspense>
  );
}
