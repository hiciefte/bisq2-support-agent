import { act, renderHook, waitFor } from "@testing-library/react";
import { useOverviewData } from "./useOverviewData";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { EMPTY_ACTION_COUNTS, type DashboardData } from "@/components/admin/overview/types";

jest.mock("@/lib/auth", () => ({
  makeAuthenticatedRequest: jest.fn(),
}));

const mockedMakeAuthenticatedRequest = makeAuthenticatedRequest as jest.MockedFunction<typeof makeAuthenticatedRequest>;

function mockJsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

const DASHBOARD_SNAPSHOT: DashboardData = {
  helpful_rate: 72.4,
  helpful_rate_trend: 1.2,
  average_response_time: 1.1,
  p95_response_time: 2.5,
  response_time_trend: -0.2,
  feedback_items_for_faq_count: 4,
  system_uptime: 99.9,
  total_queries: 90,
  total_faqs_created: 4,
  total_feedback: 20,
  total_faqs: 120,
  last_updated: "2026-02-25T12:00:00Z",
  period: "7d",
  period_label: "vs prev 7d",
};

describe("useOverviewData", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
  });

  test("refreshes dashboard and action counts together", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string) => {
      if (endpoint.startsWith("/admin/dashboard/overview")) {
        return mockJsonResponse(DASHBOARD_SNAPSHOT);
      }
      return mockJsonResponse({
        pending_escalations: 1,
        open_escalations: 2,
        actionable_signals: 3,
        covered_signals: 4,
        total_signals: 5,
        unverified_faqs: 6,
        training_queue: 7,
      });
    });

    const { result } = renderHook(() => useOverviewData({
      period: "7d",
      isInitialized: true,
      initialDashboardData: null,
      initialActionCounts: EMPTY_ACTION_COUNTS,
      refreshIntervalMs: 60_000,
    }));

    await waitFor(() => expect(result.current.dashboardData).not.toBeNull());
    expect(result.current.actionCounts.open_escalations).toBe(2);
    expect(result.current.totalOpenActions).toBe(18);
  });

  test("polls using configured interval", async () => {
    jest.useFakeTimers();
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string) => {
      if (endpoint.startsWith("/admin/dashboard/overview")) {
        return mockJsonResponse(DASHBOARD_SNAPSHOT);
      }
      return mockJsonResponse(EMPTY_ACTION_COUNTS);
    });

    renderHook(() => useOverviewData({
      period: "7d",
      isInitialized: true,
      initialDashboardData: DASHBOARD_SNAPSHOT,
      initialActionCounts: EMPTY_ACTION_COUNTS,
      refreshIntervalMs: 1_000,
    }));

    await act(async () => {
      jest.advanceTimersByTime(1_100);
      await Promise.resolve();
    });

    expect(mockedMakeAuthenticatedRequest).toHaveBeenCalledWith(
      "/admin/overview/action-counts",
    );
    expect(mockedMakeAuthenticatedRequest).toHaveBeenCalledWith(
      expect.stringMatching(/^\/admin\/dashboard\/overview\?period=7d/),
    );
    expect(mockedMakeAuthenticatedRequest.mock.calls.length).toBeGreaterThanOrEqual(4);
  });

  test("sets refresh error when both requests fail", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValue(
      mockJsonResponse({ detail: "failed" }, 500),
    );

    const { result } = renderHook(() => useOverviewData({
      period: "7d",
      isInitialized: true,
      initialDashboardData: DASHBOARD_SNAPSHOT,
      initialActionCounts: EMPTY_ACTION_COUNTS,
      refreshIntervalMs: 60_000,
    }));

    await act(async () => {
      await result.current.refresh({ background: true });
    });

    expect(result.current.error).toBe("Failed to refresh overview data.");
  });
});
