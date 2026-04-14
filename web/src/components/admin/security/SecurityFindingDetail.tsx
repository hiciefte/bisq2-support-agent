"use client";

import type { ReactNode } from "react";
import {
  Activity,
  BellRing,
  Clock3,
  Hash,
  Megaphone,
  ShieldAlert,
  Wand2,
} from "lucide-react";
import type { TrustFinding } from "@/components/admin/security/types";
import { AvatarComparison } from "@/components/admin/security/AvatarComparison";
import {
  DETECTOR_ICONS,
  DETECTOR_LABELS,
  FALLBACK_DETECTOR_ICON,
  formatRoomIdentifier,
  formatStatus,
  STATUS_STYLES,
} from "@/components/admin/security/securityUi";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SecurityFindingDetailProps {
  finding: TrustFinding | null;
  isMutating: boolean;
  onAction: (
    action: "resolve" | "false-positive" | "suppress" | "mark-benign",
  ) => void;
}

// Keys that AvatarComparison or the structured sections render explicitly —
// hide them from the generic "Other signals" grid to avoid duplication.
const STRUCTURED_KEYS = new Set([
  "suspect_avatar_url",
  "staff_avatar_url",
  "matched_staff_name",
  "user_id",
  "display_name",
  "detection_method",
  "suspect_actor_id",
  "staff_display_name",
]);

const DETECTION_METHOD_LABELS: Record<string, string> = {
  user_directory_search: "User directory match",
  public_room_scan: "Public room scan",
  message_event: "In-room message",
};

function formatAlertSurface(surface: TrustFinding["alert_surface"]): string {
  switch (surface) {
    case "admin_ui":
      return "Admin UI only";
    case "staff_room":
      return "Staff room only";
    case "both":
      return "Admin UI + staff room";
    case "none":
      return "Silent (no notifications)";
    default:
      return surface;
  }
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Never";
  }
  return new Date(value).toLocaleString();
}

function formatRoomScope(channelId: string, spaceId: string): string {
  const channel = channelId === "matrix" ? "Matrix" : channelId;
  return `${channel} · ${formatRoomIdentifier(spaceId)}`;
}

function readString(
  evidence: Record<string, unknown>,
  key: string,
): string | null {
  const value = evidence[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function riskTone(score: number): {
  label: string;
  className: string;
  barClassName: string;
} {
  if (score >= 0.9) {
    return {
      label: "Immediate review",
      className: "text-red-200",
      barClassName: "bg-red-500",
    };
  }
  if (score >= 0.75) {
    return {
      label: "High confidence",
      className: "text-amber-200",
      barClassName: "bg-amber-500",
    };
  }
  return {
    label: "Monitor closely",
    className: "text-emerald-200",
    barClassName: "bg-emerald-500",
  };
}

export function SecurityFindingDetail({
  finding,
  isMutating,
  onAction,
}: SecurityFindingDetailProps) {
  if (!finding) {
    return (
      <div
        className="rounded-2xl border border-dashed border-border/70 bg-card/40 p-6 text-sm text-muted-foreground"
        data-testid="security-finding-empty"
      >
        Select a finding to inspect the evidence summary and workflow actions.
      </div>
    );
  }

  const Icon = DETECTOR_ICONS[finding.detector_key] ?? FALLBACK_DETECTOR_ICON;
  const evidence = finding.evidence_summary;
  const suspectAvatar = readString(evidence, "suspect_avatar_url");
  const staffAvatar = readString(evidence, "staff_avatar_url");
  const matchedStaffName =
    readString(evidence, "matched_staff_name")
    ?? readString(evidence, "staff_display_name");
  const detectionMethodRaw = readString(evidence, "detection_method");
  const detectionMethod = detectionMethodRaw
    ? DETECTION_METHOD_LABELS[detectionMethodRaw] ?? humanizeKey(detectionMethodRaw)
    : null;
  const displayName = finding.suspect_display_name || finding.suspect_actor_id;
  const score = riskTone(finding.score);
  const otherSignals = Object.entries(evidence).filter(
    ([key]) => !STRUCTURED_KEYS.has(key),
  );

  return (
    <div
      className="space-y-5 rounded-2xl border border-border/70 bg-card/70 p-5"
      data-testid="security-finding-detail"
      data-finding-id={finding.id}
    >
      {/* Header: detector + status + risk score */}
      <header className="rounded-2xl border border-border/70 bg-gradient-to-br from-amber-500/10 via-background to-red-500/5 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <Icon className="h-3.5 w-3.5" />
              {DETECTOR_LABELS[finding.detector_key] ?? finding.detector_key}
            </div>
            <h2 className="text-xl font-semibold tracking-tight">
              {displayName}
            </h2>
            <p className="text-sm text-muted-foreground">
              {finding.suspect_actor_id}
            </p>
          </div>
          <Badge
            variant="outline"
            className={cn("capitalize", STATUS_STYLES[finding.status])}
          >
            {formatStatus(finding.status)}
          </Badge>
        </div>

        <div className="mt-4 space-y-3">
          <div className="flex items-baseline justify-between">
            <div className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              <ShieldAlert className="h-3.5 w-3.5" />
              Risk score
            </div>
            <div className={cn("text-sm font-semibold", score.className)}>
              {finding.score.toFixed(2)} · {score.label}
            </div>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-background/60">
            <div
              className={cn("h-full transition-all", score.barClassName)}
              style={{ width: `${Math.min(100, finding.score * 100)}%` }}
              role="progressbar"
              aria-valuenow={Math.round(finding.score * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>
      </header>

      {/* Identity comparison — the single most important visual signal */}
      {(suspectAvatar || staffAvatar || matchedStaffName) ? (
        <section aria-labelledby="finding-identity-heading" className="space-y-2">
          <div className="flex items-center gap-2">
            <h3
              id="finding-identity-heading"
              className="text-sm font-semibold text-foreground/90"
            >
              Identity comparison
            </h3>
            <span className="text-xs text-muted-foreground">
              Suspect vs. legitimate staff
            </span>
          </div>
          <AvatarComparison
            suspectAvatarUrl={suspectAvatar}
            suspectDisplayName={finding.suspect_display_name}
            suspectActorId={finding.suspect_actor_id}
            staffAvatarUrl={staffAvatar}
            staffDisplayName={matchedStaffName}
          />
        </section>
      ) : null}

      {/* Why it was flagged — structured, not flat KV */}
      <section aria-labelledby="finding-why-heading" className="space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          <h3
            id="finding-why-heading"
            className="text-sm font-semibold text-foreground/90"
          >
            Why it was flagged
          </h3>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          {detectionMethod ? (
            <DataRow
              icon={<Wand2 className="h-3.5 w-3.5" />}
              label="Detection method"
              value={detectionMethod}
            />
          ) : null}
          {matchedStaffName ? (
            <DataRow
              icon={<Hash className="h-3.5 w-3.5" />}
              label="Collides with staff name"
              value={matchedStaffName}
              accent
            />
          ) : null}
          <DataRow
            icon={<Megaphone className="h-3.5 w-3.5" />}
            label="Alert destination"
            value={formatAlertSurface(finding.alert_surface)}
          />
          <DataRow
            icon={<BellRing className="h-3.5 w-3.5" />}
            label="Alert fan-out"
            value={
              finding.notification_count > 0
                ? `${finding.notification_count}× notified`
                : "Shadow only"
            }
            hint={`Last notified ${formatTimestamp(finding.last_notified_at)}`}
          />
          <DataRow
            icon={<Hash className="h-3.5 w-3.5" />}
            label="Room scope"
            value={formatRoomScope(finding.channel_id, finding.space_id)}
          />
          <DataRow
            icon={<Clock3 className="h-3.5 w-3.5" />}
            label="Last updated"
            value={formatTimestamp(finding.updated_at)}
            hint={`Opened ${formatTimestamp(finding.created_at)}`}
          />
        </dl>

        {otherSignals.length > 0 ? (
          <details className="rounded-xl border border-border/60 bg-background/40 p-3 text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none font-medium text-foreground/80">
              Other signals ({otherSignals.length})
            </summary>
            <dl className="mt-2 grid gap-2 sm:grid-cols-2">
              {otherSignals.map(([key, value]) => (
                <div key={key} className="rounded-lg bg-background/60 px-3 py-2">
                  <dt className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    {humanizeKey(key)}
                  </dt>
                  <dd className="mt-1 break-words text-xs text-foreground/85">
                    {String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}
      </section>

      {/* Review actions — primary + secondary hierarchy */}
      <section
        aria-labelledby="finding-actions-heading"
        className="rounded-xl border border-border/70 bg-background/35 p-4"
      >
        <h3
          id="finding-actions-heading"
          className="text-sm font-semibold text-foreground/90"
        >
          Review decision
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Resolve confirmed risks. Mark benign for verified safe behavior.
          Suppress to silence the actor temporarily. Mark false positive when
          the detector misfired.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => onAction("resolve")}
            disabled={isMutating}
            className="bg-red-600 text-white hover:bg-red-500 focus-visible:ring-red-500"
            data-action="primary"
          >
            Resolve finding
          </Button>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onAction("mark-benign")}
              disabled={isMutating}
            >
              Mark benign
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onAction("suppress")}
              disabled={isMutating}
            >
              Suppress actor
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onAction("false-positive")}
              disabled={isMutating}
            >
              False positive
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}

interface DataRowProps {
  icon: ReactNode;
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}

function DataRow({ icon, label, value, hint, accent }: DataRowProps) {
  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3",
        accent
          ? "border-amber-500/40 bg-amber-500/10"
          : "border-border/60 bg-background/50",
      )}
    >
      <dt className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {icon}
        {label}
      </dt>
      <dd
        className={cn(
          "mt-2 text-sm font-medium",
          accent ? "text-amber-100" : "text-foreground/90",
        )}
      >
        {value}
      </dd>
      {hint ? (
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
