"use client";

import { useCallback, useEffect, useState } from "react";
import { makeAuthenticatedRequest } from "@/lib/auth";
import {
  type AdminActionCounts,
  EMPTY_ACTION_COUNTS,
} from "@/components/admin/overview/types";

export function useAdminActionCounts(
  refreshIntervalMs = 60000,
  autoRefresh = true,
): {
  counts: AdminActionCounts;
  isLoading: boolean;
  refresh: () => Promise<void>;
} {
  const [counts, setCounts] = useState<AdminActionCounts>(EMPTY_ACTION_COUNTS);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest("/admin/overview/action-counts");
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      setCounts({
        pending_escalations: Number(payload.pending_escalations || 0),
        open_escalations: Number(payload.open_escalations || 0),
        actionable_signals: Number(payload.actionable_signals || 0),
        covered_signals: Number(payload.covered_signals || 0),
        total_signals: Number(payload.total_signals || 0),
        unverified_faqs: Number(payload.unverified_faqs || 0),
        training_queue: Number(payload.training_queue || 0),
      });
    } catch {
      // Non-critical UI helper. Keep previous values.
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!autoRefresh) {
      return undefined;
    }

    let cancelled = false;

    const run = async () => {
      if (cancelled) return;
      await refresh();
    };

    void run();
    const intervalId = setInterval(() => {
      void run();
    }, refreshIntervalMs);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [autoRefresh, refresh, refreshIntervalMs]);

  return { counts, isLoading, refresh };
}
