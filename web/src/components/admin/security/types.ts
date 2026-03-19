export type TrustAlertSurface = "admin_ui" | "staff_room" | "both" | "none";
export type TrustFindingStatus = "open" | "resolved" | "false_positive" | "suppressed" | "benign";
export type TrustDetectorKey = "staff_name_collision" | "silent_early_observer";

export interface TrustMonitorPolicy {
  enabled: boolean;
  name_collision_enabled: boolean;
  silent_observer_enabled: boolean;
  alert_surface: TrustAlertSurface;
  matrix_public_room_ids: string[];
  matrix_staff_room_id: string;
  silent_observer_window_days: number;
  early_read_window_seconds: number;
  minimum_observations: number;
  minimum_early_read_hits: number;
  read_to_reply_ratio_threshold: number;
  evidence_ttl_days: number;
  aggregate_ttl_days: number;
  finding_ttl_days: number;
  updated_at: string;
}

export interface TrustFinding {
  id: number;
  detector_key: TrustDetectorKey;
  channel_id: string;
  space_id: string;
  suspect_actor_id: string;
  suspect_display_name: string;
  score: number;
  status: TrustFindingStatus;
  alert_surface: TrustAlertSurface;
  evidence_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_notified_at: string | null;
  notification_count: number;
}

export interface TrustFindingListResponse {
  items: TrustFinding[];
  total: number;
}

export interface TrustFindingCounts {
  total: number;
  open: number;
  resolved: number;
  false_positive: number;
  suppressed: number;
  benign: number;
}

export interface TrustRetentionRun {
  id: number;
  created_at: string;
  deleted_evidence_events: number;
  deleted_actor_aggregates: number;
  deleted_findings: number;
  deleted_feedback: number;
  deleted_access_audit: number;
}

export interface TrustMonitorOpsSnapshot {
  monitored_public_rooms: string[];
  staff_room_id: string;
  evidence_events_count: number;
  actor_aggregates_count: number;
  findings_count: number;
  oldest_evidence_age_seconds: number | null;
  oldest_aggregate_age_seconds: number | null;
  oldest_finding_age_seconds: number | null;
  last_retention_run: TrustRetentionRun | null;
}

export interface TrustAccessAuditEntry {
  id: number;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TrustAccessAuditListResponse {
  items: TrustAccessAuditEntry[];
}

export interface ChatOpsAuditEntry {
  id: number;
  channel_id: string;
  room_id: string;
  actor_id: string;
  command_name: string;
  case_id: number | null;
  source_message_id: string;
  ok: boolean;
  idempotent: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ChatOpsAuditListResponse {
  items: ChatOpsAuditEntry[];
}

export interface SecurityAlertsInitialData {
  findings: TrustFindingListResponse | null;
  counts: TrustFindingCounts | null;
  policy: TrustMonitorPolicy | null;
  ops: TrustMonitorOpsSnapshot | null;
  trustAudit: TrustAccessAuditListResponse | null;
  chatopsAudit: ChatOpsAuditListResponse | null;
}
