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

export interface SecurityAlertsInitialData {
  findings: TrustFindingListResponse | null;
  counts: TrustFindingCounts | null;
  policy: TrustMonitorPolicy | null;
}
