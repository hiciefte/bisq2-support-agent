import type { TrustMonitorPolicy } from "@/components/admin/security/types";

export type ChannelId = "web" | "bisq2" | "matrix";
export type EscalationNotificationChannel = "public_room" | "staff_room" | "none";

export interface ChannelAutoresponsePolicy {
  channel_id: ChannelId;
  enabled: boolean;
  generation_enabled: boolean;
  ai_response_mode: "autonomous" | "hitl";
  hitl_approval_timeout_seconds: number;
  draft_assistant_enabled: boolean;
  knowledge_amplifier_enabled: boolean;
  staff_assist_surface: "none" | "staff_room" | "admin_ui" | "both";
  first_response_delay_seconds: number;
  staff_active_cooldown_seconds: number;
  max_proactive_ai_replies_per_question: number;
  public_escalation_notice_enabled: boolean;
  acknowledgment_mode: "none" | "reaction" | "message";
  acknowledgment_reaction_key: string;
  acknowledgment_message_template: string;
  group_clarification_immediate: boolean;
  escalation_user_notice_template: string;
  escalation_user_notice_mode: "none" | "message";
  dispatch_failure_message_template: string;
  escalation_notification_channel: EscalationNotificationChannel;
  explicit_invocation_enabled: boolean;
  explicit_invocation_user_rate_limit_per_5m: number;
  explicit_invocation_room_rate_limit_per_min: number;
  community_response_cancels_ai: boolean;
  community_substantive_min_chars: number;
  staff_presence_aware_delay: boolean;
  min_delay_no_staff_seconds: number;
  mandatory_escalation_topics: string[];
  timer_jitter_max_seconds: number;
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
  actionCounts: AdminActionCounts | null;
  channelPolicies: ChannelAutoresponsePolicy[];
  trustMonitorPolicy: TrustMonitorPolicy | null;
}
