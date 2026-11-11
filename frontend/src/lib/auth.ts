"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { api, ApiError, type User } from "./api";

export function useMe() {
  return useQuery<User, ApiError>({ queryKey: ["me"], queryFn: () => api<User>("/me") });
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      /* 이미 만료된 세션이어도 화면은 로그인으로 보낸다 */
    }
    qc.clear();
    router.replace("/login");
  }, [qc, router]);
}
