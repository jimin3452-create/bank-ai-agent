"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api, won, type AccountDetail } from "@/lib/api";
import { Button, Card, ErrorBox, PageHeader, PinSheet, Spinner, useToast } from "@/components/ui";

type Check = { closable: boolean; reasons: { code: string; message: string }[] };

// 막힌 사유별로 바로 해결할 수 있는 화면을 안내한다.
const FIX: Record<string, (id: string) => { href: string; label: string }> = {
  BALANCE_REMAINING: (id) => ({ href: `/transfer?from_account_id=${id}`, label: "잔액 이체하기" }),
  CARD_LINKED: () => ({ href: "/cards", label: "카드 관리" }),
  AUTO_TRANSFER_ACTIVE: () => ({ href: "/auto-transfers", label: "자동이체 관리" }),
};

export default function CloseAccountPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const acc = useQuery({ queryKey: ["account", id], queryFn: () => api<AccountDetail>(`/accounts/${id}`) });
  const check = useQuery({ queryKey: ["close-check", id], queryFn: () => api<Check>(`/accounts/${id}/close-check`), staleTime: 0 });
  const [agree, setAgree] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);

  return (
    <>
      <PageHeader title="계좌 해지" back={`/accounts/${id}/manage`} />
      <main className="space-y-4 p-4">
        {acc.data && (
          <Card>
            <p className="font-semibold">{acc.data.nickname ?? acc.data.product_name}</p>
            <p className="tabular text-[13px] text-sub">{acc.data.account_num} · {won(acc.data.balance)}</p>
          </Card>
        )}
        {check.isPending ? <Spinner label="해지 가능 여부를 확인하는 중…" /> : check.error ? <ErrorBox error={check.error} /> : check.data.closable ? (
          <>
            <Card className="space-y-2 text-[13px] text-sub">
              <p className="text-[15px] font-bold text-ink">해지하기 전에 확인해 주세요</p>
              <p>· 해지한 계좌는 다시 사용할 수 없어요.</p>
              <p>· 거래내역은 보관되지만 새 거래는 할 수 없어요.</p>
            </Card>
            <label className="flex items-center gap-2 text-[14px]">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> 위 내용을 확인했고 해지에 동의해요
            </label>
            <Button block variant="danger" disabled={!agree} onClick={() => setPinOpen(true)}>해지하기</Button>
          </>
        ) : (
          <Card className="space-y-3">
            <p className="text-[15px] font-bold text-danger">지금은 해지할 수 없어요</p>
            {check.data.reasons.map((r) => {
              const fix = FIX[r.code]?.(id);
              return (
                <div key={r.code} className="rounded-xl bg-danger-soft p-3 text-[13px] text-danger">
                  <p>{r.message}</p>
                  {fix && <Link href={fix.href} className="mt-1 inline-block font-semibold underline">{fix.label} →</Link>}
                </div>
              );
            })}
            <Button block variant="ghost" onClick={() => check.refetch()}>다시 확인</Button>
          </Card>
        )}
      </main>
      <PinSheet open={pinOpen} onClose={() => setPinOpen(false)} title="계좌 해지" description="PIN을 입력하면 계좌가 해지돼요."
        onSubmit={async (pin) => {
          await api(`/accounts/${id}/close`, { method: "POST", body: { pin } });
          await qc.invalidateQueries({ queryKey: ["accounts"] });
          toast("계좌를 해지했어요");
          router.replace("/home");
        }} />
    </>
  );
}
