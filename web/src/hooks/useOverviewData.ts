"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AdminActionCounts,
  DashboardData,
} from "@/components/admin/overview/types";
import { EMPTY_ACTION_COUNTS } from "@/components/admin/overview/types";
import { makeAuthenticatedRequest } from "@/lib/auth";
import type { Period } from "@/types/dashboard";

interface UseOverviewDataOptions {
  period: Period;
  dateRange?: { from: Date; to: Date };
  isInitialized: boolean;
  initialDashboardData: DashboardData | null;
  initialActionCounts: AdminActionCounts;
  refreshIntervalMs?: number;
}

function buildDashboardPath(period: Period, dateRange?: { from: Date; to: Date }): string {
  const params = new URLSearchParams();
  params.set("period", period);

  if (period === "custom" && dateRange) {
    params.set("start_date", dateRange.from.toISOString());
    params.set("end_date", dateRange.to.toISOString());
  }

  return `/admin/dashboard/overview?${params.toString()}`;
}

async function requestDashboard(
  period: Period,
  dateRange?: { from: Date; to: Date },
): Promise<DashboardData> {
  const response = await makeAuthenticatedRequest(buildDashboardPath(period, dateRange));
  if (!response.ok) {
    throw new Error(`Dashboard request failed with status ${response.status}`);
  }
  return (await response.json()) as DashboardData;
}

async function requestActionCounts(): Promise<AdminActionCounts> {
  const response = await makeAuthenticatedRequest("/admin/overview/action-counts");
  if (!response.ok) {
    throw new Error(`Action-counts request failed with status ${response.status}`);
  }

  const payload = await response.json();
  return {
    pending_escalations: Number(payload.pending_escalations || 0),
    open_escalations: Number(payload.open_escalations || 0),
    actionable_signals: Number(payload.actionable_signals || 0),
    covered_signals: Number(payload.covered_signals || 0),
    total_signals: Number(payload.total_signals || 0),
    unverified_faqs: Number(payload.unverified_faqs || 0),
    training_queue: Number(payload.training_queue || 0),
  };
}

export function useOverviewData({
  period,
  dateRange,
  isInitialized,
  initialDashboardData,
  initialActionCounts,
  refreshIntervalMs = 30000,
}: UseOverviewDataOptions) {
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(initialDashboardData);
  const [actionCounts, setActionCounts] = useState<AdminActionCounts>(
    initialActionCounts ?? EMPTY_ACTION_COUNTS,
  );
  const [isLoading, setIsLoading] = useState(initialDashboardData === null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestFetchIdRef = useRef(0);
  const hasLoadedOnceRef = useRef(initialDashboardData !== null);

  const fetchSnapshot = useCallback(async (
    options: {
      background?: boolean;
    } = {},
  ) => {
    const requestId = ++latestFetchIdRef.current;
    const { background = false } = options;
    const runInBackground = background || hasLoadedOnceRef.current;

    if (runInBackground) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    try {
      const [dashboardResult, countsResult] = await Promise.allSettled([
        requestDashboard(period, dateRange),
        requestActionCounts(),
      ]);

      if (requestId !== latestFetchIdRef.current) {
        return;
      }

      const dashboardFailed = dashboardResult.status === "rejected";
      const countsFailed = countsResult.status === "rejected";

      if (!dashboardFailed) {
        setDashboardData(dashboardResult.value);
        hasLoadedOnceRef.current = true;
      } else {
        console.error("Overview dashboard fetch error:", dashboardResult.reason);
      }

      if (!countsFailed) {
        setActionCounts(countsResult.value);
      } else {
        console.error("Overview action-counts fetch error:", countsResult.reason);
      }

      if (dashboardFailed && countsFailed) {
        setError("Failed to refresh overview data.");
      } else {
        setError(null);
      }
    } finally {
      if (requestId === latestFetchIdRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [dateRange, period]);

  useEffect(() => {
    if (!isInitialized) return;

    void fetchSnapshot();
    const intervalId = window.setInterval(() => {
      void fetchSnapshot({ background: true });
    }, refreshIntervalMs);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [fetchSnapshot, isInitialized, refreshIntervalMs]);

  const totalOpenActions = useMemo(
    () =>
      actionCounts.actionable_signals
      + actionCounts.open_escalations
      + actionCounts.unverified_faqs
      + actionCounts.training_queue,
    [actionCounts],
  );

  return {
    dashboardData,
    actionCounts,
    totalOpenActions,
    isLoading,
    isRefreshing,
    error,
    refresh: fetchSnapshot,
  };
}
