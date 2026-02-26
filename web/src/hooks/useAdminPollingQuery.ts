"use client";

import {
  type QueryFunction,
  type QueryKey,
  useQuery,
  type UseQueryOptions,
} from "@tanstack/react-query";

interface UseAdminPollingQueryOptions<TData, TQueryKey extends QueryKey>
  extends Omit<UseQueryOptions<TData, Error, TData, TQueryKey>, "queryKey" | "queryFn"> {
  queryKey: TQueryKey;
  queryFn: QueryFunction<TData, TQueryKey>;
  refetchIntervalMs?: number;
}

function shouldPollNow(): boolean {
  if (typeof document === "undefined") return true;
  return document.visibilityState === "visible";
}

export function useAdminPollingQuery<TData, TQueryKey extends QueryKey>({
  queryKey,
  queryFn,
  refetchIntervalMs = 30_000,
  enabled = true,
  ...rest
}: UseAdminPollingQueryOptions<TData, TQueryKey>) {
  return useQuery<TData, Error, TData, TQueryKey>({
    queryKey,
    queryFn,
    enabled,
    refetchInterval: () => (shouldPollNow() ? refetchIntervalMs : false),
    ...rest,
  });
}
