import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { OverviewClient } from "./OverviewClient";

jest.mock("next/link", () => ({
  __esModule: true,
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return new Proxy({}, { get: () => MockIcon });
});

const trustMonitoringCardSpy = jest.fn(() => <div>trust-monitor-card</div>);

jest.mock("@/components/admin/overview/TrustMonitoringCard", () => ({
  TrustMonitoringCard: (props: unknown) => trustMonitoringCardSpy(props),
}));

jest.mock("@/components/admin/overview/ChannelAutoresponseCard", () => ({
  ChannelAutoresponseCard: () => <div>channel-autoresponse-card</div>,
}));

jest.mock("@/hooks/usePeriodStorage", () => ({
  usePeriodStorage: () => ({
    period: "7d",
    dateRange: null,
    updatePeriod: jest.fn(),
    isInitialized: true,
  }),
}));

jest.mock("@/hooks/useOverviewData", () => ({
  useOverviewData: () => ({
    dashboardData: {
      total_feedback: 12,
      total_queries: 20,
      helpful_rate: 75,
      last_updated: "2026-03-19T10:00:00Z",
      fallback: false,
      period_label: "Last 7 days",
      system_uptime: 3600,
      total_faqs_created: 5,
      avg_response_time: 1.2,
      avg_retrieval_time: 0.4,
      avg_generation_time: 0.8,
      cache_hit_rate: 45,
      response_time_trend: 0,
      helpful_rate_trend: 0,
      query_volume_trend: 0,
      retrieval_time_trend: 0,
      generation_time_trend: 0,
      cache_hit_rate_trend: 0,
    },
    actionCounts: {
      actionable_signals: 0,
      open_escalations: 0,
      pending_escalations: 0,
      unverified_faqs: 0,
      covered_signals: 0,
      total_signals: 0,
      training_queue: 0,
    },
    isActionCountsAvailable: true,
    totalOpenActions: 0,
    isLoading: false,
    isRefreshing: false,
    error: null,
    refresh: jest.fn(),
  }),
}));

jest.mock("@/hooks/useChannelAutoresponsePolicies", () => ({
  useChannelAutoresponsePolicies: () => ({
    policies: [],
    isLoading: false,
    isSavingByChannel: {},
    error: null,
    refresh: jest.fn(),
    setChannelMode: jest.fn(),
    setEscalationNotificationChannel: jest.fn(),
    setAcknowledgmentMode: jest.fn(),
    setAcknowledgmentReactionKey: jest.fn(),
    setAcknowledgmentMessageTemplate: jest.fn(),
    setEscalationUserNoticeMode: jest.fn(),
  }),
}));

jest.mock("@/hooks/useTrustMonitorPolicy", () => ({
  useTrustMonitorPolicy: () => ({
    policy: {
      enabled: true,
      name_collision_enabled: true,
      silent_observer_enabled: true,
      alert_surface: "admin_ui",
      matrix_public_room_ids: ["!support:matrix.org"],
      matrix_staff_room_id: "!staff:matrix.org",
      silent_observer_window_days: 14,
      early_read_window_seconds: 30,
      minimum_observations: 10,
      minimum_early_read_hits: 8,
      read_to_reply_ratio_threshold: 12,
      evidence_ttl_days: 7,
      aggregate_ttl_days: 30,
      finding_ttl_days: 30,
      updated_at: "2026-03-19T10:00:00Z",
    },
    isLoading: false,
    isSaving: false,
    error: null,
    refresh: jest.fn(),
    setEnabled: jest.fn(),
    setDetectorEnabled: jest.fn(),
    setAlertSurface: jest.fn(),
  }),
}));

describe("OverviewClient", () => {
  test("renders trust monitoring collapsed by default on the overview page", () => {
    render(
      <OverviewClient
        initialData={{
          dashboardData: null as never,
          actionCounts: null as never,
          channelPolicies: [],
          trustMonitorPolicy: null,
        }}
      />,
    );

    expect(screen.getByText("trust-monitor-card")).toBeInTheDocument();
    expect(trustMonitoringCardSpy).toHaveBeenCalledWith(
      expect.objectContaining({ defaultCollapsed: true }),
    );
  });
});
