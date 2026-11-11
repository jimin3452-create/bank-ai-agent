"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, won, type AccountSummary, type Card as CardT } from "@/lib/api";
import { Button, ErrorBox, Field, MoneyInput, PageHeader, Select, Spinner } from "@/components/ui";

const MIN = 10_000;
const MAX = 10_000_000;

export default function Page() {
  return (
    <Suspense fallback={<Spinner />}>
      <NewCard />
    </Suspense>
  );
}

function NewCard() {
  const router = useRouter();
  const sp = useSearchParams();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountSummary[]>("/accounts") });
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<CardT[]>("/cards") });
  const usable = (accounts.data ?? []).filter((a) => a.status === "ACTIVE");

  const [accountSel, setAccountId] = useState(sp.get("account_id") ?? "");
  const [network, setNetwork] = useState("LOCAL");
  const [limit, setLimit] = useState("1000000");
  const [overseas, setOverseas] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const accountId = accountSel || usable[0]?.id || "";

  const hasCard = cards.data?.some((c) => c.account_id === accountId && ["ACTIVE", "SUSPENDED", "LOST"].includes(c.status));
  const n = Number(limit || 0);
  const limitErr = n < MIN || n > MAX ? `일일 한도는 ${won(MIN)} ~ ${won(MAX)} 사이로 정해 주세요.` : null;

  async function issue() {
    setBusy(true);
    setErr(null);
    try {
      const c = await api<CardT>("/cards", { method: "POST", body: { account_id: accountId, card_network: network, daily_limit: n, overseas_enabled: overseas } });
      await qc.invalidateQueries({ queryKey: ["cards"] });
      router.replace(`/cards/${c.id}`);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="체크카드 발급" back="/cards" />
      <main className="space-y-5 p-4">
        {accounts.isPending ? <Spinner /> : (
          <>
            <Field label="연결 계좌" hint="계좌 하나에 사용 중인 카드는 1장만 만들 수 있어요.">
              <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                {usable.map((a) => <option key={a.id} value={a.id}>{a.nickname ?? a.product_name} · {a.account_num_masked}</option>)}
              </Select>
            </Field>
            <Field label="브랜드">
              <Select value={network} onChange={(e) => setNetwork(e.target.value)}>
                <option value="LOCAL">국내 전용</option>
                <option value="VISA">VISA</option>
                <option value="MASTER">MASTER</option>
              </Select>
            </Field>
            <Field label="일일 사용한도" error={limitErr}>
              <MoneyInput value={limit} onChange={setLimit} />
            </Field>
            <label className="flex items-center justify-between rounded-xl border border-line bg-surface px-4 py-3">
              <span className="text-[15px]">해외 결제 허용</span>
              <input type="checkbox" checked={overseas} onChange={(e) => setOverseas(e.target.checked)} className="h-5 w-5 accent-[#16805d]" />
            </label>
            {hasCard && <p className="rounded-xl bg-warn-soft px-3.5 py-3 text-[13px] text-warn">이 계좌에는 이미 사용 중인 카드가 있어요. 재발급이나 해지를 이용해 주세요.</p>}
            <ErrorBox error={err} />
            <Button block loading={busy} disabled={!accountId || !!limitErr || !!hasCard} onClick={issue}>발급하기</Button>
          </>
        )}
      </main>
    </>
  );
}
