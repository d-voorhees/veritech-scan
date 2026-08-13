"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    throwOnError: false,
  });
}

export function useRequireAuth() {
  const router = useRouter();
  const query = useMe();

  if (query.isError && query.error instanceof ApiError && query.error.status === 401) {
    if (typeof window !== "undefined") router.replace("/login");
  }

  return query;
}

export function useLogin() {
  const queryClient = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => api.login(email, password),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.push("/dashboard");
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      queryClient.clear();
      router.push("/login");
    },
  });
}
