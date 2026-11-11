// 브라우저 → /api/* (Next rewrites → FastAPI). 쿠키 인증이라 credentials 는 same-origin 기본값으로 충분하다.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public field: string | null = null,
  ) {
    super(message);
  }
}

type Opts = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  headers?: Record<string, string>;
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, query, headers = {} } = opts;
  let url = `/api${path}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new ApiError(res.status, data?.code ?? "ERROR", data?.message ?? "요청을 처리하지 못했습니다.", data?.field ?? null);
    // 세션 만료만 로그인으로 보낸다(PIN·통장 비밀번호 오류도 401이라 코드로 구분한다)
    if (res.status === 401 && err.code === "UNAUTHENTICATED" && !path.startsWith("/auth/")) onUnauthorized?.();
    throw err;
  }
  return data as T;
}

export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

export function fmtDateTime(iso: string) {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function fmtDate(iso: string) {
  return fmtDateTime(iso).slice(0, 10);
}

export function newKey() {
  return crypto.randomUUID();
}

// --- 응답 타입(백엔드 실제 응답 기준) ---
export type User = {
  id: string;
  login_id: string;
  user_name: string;
  email: string;
  phone_num: string;
  birth: string | null;
  status: string;
  created_at: string;
};
export type AccountSummary = {
  id: string;
  nickname: string | null;
  product_name: string;
  account_num_masked: string;
  balance: number;
  status: string;
  is_favorite: boolean;
};
export type AccountDetail = AccountSummary & {
  account_num: string;
  interest_rate: number;
  daily_limit: number;
  month_limit: number;
  created_at: string;
  closed_at: string | null;
};
export type Tx = {
  id: number;
  type: "DEPOSIT" | "WITHDRAW" | "TRANSFER" | "AUTO_TRANSFER" | "CARD";
  direction: "IN" | "OUT";
  amount: number;
  new_balance: number;
  counterparty_name: string | null;
  memo: string | null;
  transaction_at: string;
};
export type Card = {
  id: string;
  account_id: string;
  card_number_masked: string;
  last4: string;
  expiry_date: string;
  card_network: string;
  daily_limit: number;
  overseas_enabled: boolean;
  status: string;
  reissued_from_id: string | null;
  created_at: string;
};
export type Notification = { id: number; type: string; message: string; read_at: string | null; created_at: string };
export type AgentLink = { label: string; screen_id: string; route: string };
export type AgentReply = {
  session_id: string;
  reply: string;
  evidence: unknown[];
  sources: unknown[];
  links: AgentLink[];
  pending_action: { action_id: string; summary: string } | null;
  degraded?: boolean;
  session_renewed?: boolean;
};
