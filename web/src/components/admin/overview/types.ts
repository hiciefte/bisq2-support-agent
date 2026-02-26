export type ChannelId = "web" | "bisq2" | "matrix";

export interface ChannelAutoresponsePolicy {
  channel_id: ChannelId;
  enabled: boolean;
  generation_enabled: boolean;
  updated_at: string;
}

export interface DashboardData {
  helpful_rate: number;
  helpful_rate_trend: number;
  average_response_time: number;
  p95_response_time: number | null;
  response_time_trend: number;
  feedback_items_for_faq_count: number;
  system_uptime: number;
  total_queries: number;
  total_faqs_created: number;
  total_feedback: number;
  total_faqs: number;
  last_updated: string;
  fallback?: boolean;
  period: string;
  period_label: string;
  period_start?: string;
  period_end?: string;
}

export interface AdminActionCounts {
  pending_escalations: number;
  open_escalations: number;
  actionable_signals: number;
  covered_signals: number;
  total_signals: number;
  unverified_faqs: number;
  training_queue: number;
}

export const EMPTY_ACTION_COUNTS: AdminActionCounts = {
  pending_escalations: 0,
  open_escalations: 0,
  actionable_signals: 0,
  covered_signals: 0,
  total_signals: 0,
  unverified_faqs: 0,
  training_queue: 0,
};

export interface OverviewInitialData {
  dashboardData: DashboardData | null;
  actionCounts: AdminActionCounts;
  channelPolicies: ChannelAutoresponsePolicy[];
}
