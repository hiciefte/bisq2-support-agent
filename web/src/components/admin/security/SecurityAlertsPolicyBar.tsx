"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { TrustAlertSurface, TrustMonitorPolicy } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface SecurityAlertsPolicyBarProps {
  policy: TrustMonitorPolicy | null;
  isSaving: boolean;
  onAlertSurfaceChange: (surface: TrustAlertSurface) => void;
  onPolicyPatch: (patch: Partial<TrustMonitorPolicy>) => Promise<boolean>;
}

function surfaceLabel(surface: TrustAlertSurface | undefined): string {
  switch (surface) {
    case "staff_room":
      return "Staff Room Live";
    case "both":
      return "Admin UI + Staff Room";
    case "none":
      return "Muted";
    default:
      return "Admin UI Shadow";
  }
}

export function SecurityAlertsPolicyBar({
  policy,
  isSaving,
  onAlertSurfaceChange,
  onPolicyPatch,
}: SecurityAlertsPolicyBarProps) {
  const currentSurface = policy?.alert_surface ?? "admin_ui";
  const [draft, setDraft] = useState({
    silent_observer_window_days: policy?.silent_observer_window_days ?? 14,
    early_read_window_seconds: policy?.early_read_window_seconds ?? 30,
    minimum_observations: policy?.minimum_observations ?? 10,
    minimum_early_read_hits: policy?.minimum_early_read_hits ?? 8,
    read_to_reply_ratio_threshold: policy?.read_to_reply_ratio_threshold ?? 12,
    evidence_ttl_days: policy?.evidence_ttl_days ?? 7,
    aggregate_ttl_days: policy?.aggregate_ttl_days ?? 30,
    finding_ttl_days: policy?.finding_ttl_days ?? 30,
  });

  useEffect(() => {
    setDraft({
      silent_observer_window_days: policy?.silent_observer_window_days ?? 14,
      early_read_window_seconds: policy?.early_read_window_seconds ?? 30,
      minimum_observations: policy?.minimum_observations ?? 10,
      minimum_early_read_hits: policy?.minimum_early_read_hits ?? 8,
      read_to_reply_ratio_threshold: policy?.read_to_reply_ratio_threshold ?? 12,
      evidence_ttl_days: policy?.evidence_ttl_days ?? 7,
      aggregate_ttl_days: policy?.aggregate_ttl_days ?? 30,
      finding_ttl_days: policy?.finding_ttl_days ?? 30,
    });
  }, [policy]);

  const hasAdvancedChanges = Boolean(
    policy && (
      draft.silent_observer_window_days !== policy.silent_observer_window_days
      || draft.early_read_window_seconds !== policy.early_read_window_seconds
      || draft.minimum_observations !== policy.minimum_observations
      || draft.minimum_early_read_hits !== policy.minimum_early_read_hits
      || draft.read_to_reply_ratio_threshold !== policy.read_to_reply_ratio_threshold
      || draft.evidence_ttl_days !== policy.evidence_ttl_days
      || draft.aggregate_ttl_days !== policy.aggregate_ttl_days
      || draft.finding_ttl_days !== policy.finding_ttl_days
    )
  );

  return (
    <div className="rounded-2xl border border-border/70 bg-card/70 px-4 py-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Security Alerts</h1>
            <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
              {surfaceLabel(currentSurface)}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Review trust-monitor findings before promoting them into the staff room.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={isSaving || currentSurface === "staff_room"}
            onClick={() => onAlertSurfaceChange("staff_room")}
          >
            Promote to Staff Room
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isSaving || currentSurface === "admin_ui"}
            onClick={() => onAlertSurfaceChange("admin_ui")}
          >
            Return to Admin UI Only
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isSaving || currentSurface === "both"}
            onClick={() => onAlertSurfaceChange("both")}
          >
            Mirror to Both
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isSaving || currentSurface === "none"}
            onClick={() => onAlertSurfaceChange("none")}
          >
            Mute Alerts
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link href="/admin/overview">Overview controls</Link>
          </Button>
        </div>
      </div>

      <details className="mt-4 rounded-xl border border-border/70 bg-background/35 px-4 py-3">
        <summary className="cursor-pointer list-none text-sm font-medium">
          Advanced controls
        </summary>
        <p className="mt-2 text-xs text-muted-foreground">
          Tune thresholds and retention directly from admin without changing env config.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <NumberField label="Window (days)" value={draft.silent_observer_window_days} onChange={(value) => setDraft((current) => ({ ...current, silent_observer_window_days: value }))} />
          <NumberField label="Early read (s)" value={draft.early_read_window_seconds} onChange={(value) => setDraft((current) => ({ ...current, early_read_window_seconds: value }))} />
          <NumberField label="Min observations" value={draft.minimum_observations} onChange={(value) => setDraft((current) => ({ ...current, minimum_observations: value }))} />
          <NumberField label="Min hits" value={draft.minimum_early_read_hits} onChange={(value) => setDraft((current) => ({ ...current, minimum_early_read_hits: value }))} />
          <NumberField label="Read/reply ratio" value={draft.read_to_reply_ratio_threshold} step="0.5" onChange={(value) => setDraft((current) => ({ ...current, read_to_reply_ratio_threshold: value }))} />
          <NumberField label="Evidence TTL (days)" value={draft.evidence_ttl_days} onChange={(value) => setDraft((current) => ({ ...current, evidence_ttl_days: value }))} />
          <NumberField label="Aggregate TTL (days)" value={draft.aggregate_ttl_days} onChange={(value) => setDraft((current) => ({ ...current, aggregate_ttl_days: value }))} />
          <NumberField label="Finding TTL (days)" value={draft.finding_ttl_days} onChange={(value) => setDraft((current) => ({ ...current, finding_ttl_days: value }))} />
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground">
            Public rooms: {(policy?.matrix_public_room_ids ?? []).join(", ") || "Not configured"} · Staff room: {policy?.matrix_staff_room_id || "Not configured"}
          </div>
          <Button
            size="sm"
            disabled={isSaving || !hasAdvancedChanges}
            onClick={() => void onPolicyPatch(draft)}
          >
            Save advanced controls
          </Button>
        </div>
      </details>
    </div>
  );
}

function NumberField({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number;
  step?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium">{label}</span>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
      />
    </label>
  );
}
