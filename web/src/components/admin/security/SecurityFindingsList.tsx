"use client";

import { Clock3, Radar, ShieldAlert, Siren } from "lucide-react";
import type { TrustFinding } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface SecurityFindingsListProps {
  findings: TrustFinding[];
  selectedFindingId: number | null;
  onSelect: (findingId: number) => void;
}

const DETECTOR_LABELS: Record<TrustFinding["detector_key"], string> = {
  staff_name_collision: "Staff Name Collision",
  silent_early_observer: "Silent Observer",
};

const DETECTOR_DESCRIPTIONS: Record<TrustFinding["detector_key"], string> = {
  staff_name_collision: "Trusted identity mismatch in a public support room.",
  silent_early_observer: "High read activity with unusually low reply participation.",
};

const DETECTOR_ICONS = {
  staff_name_collision: ShieldAlert,
  silent_early_observer: Radar,
} satisfies Record<TrustFinding["detector_key"], typeof ShieldAlert>;

const STATUS_STYLES: Record<TrustFinding["status"], string> = {
  open: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  resolved: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  false_positive: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  suppressed: "border-zinc-500/30 bg-zinc-500/10 text-zinc-200",
  benign: "border-violet-500/30 bg-violet-500/10 text-violet-200",
};

function formatStatus(status: TrustFinding["status"]): string {
  return status.replace(/_/g, " ");
}

function formatRelativeTime(value: string): string {
  const diffMs = Date.now() - new Date(value).getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));

  if (diffMinutes < 1) {
    return "just now";
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }

  return `${Math.floor(diffHours / 24)}d ago`;
}

function scoreTone(score: number): string {
  if (score >= 0.9) {
    return "text-red-300";
  }
  if (score >= 0.75) {
    return "text-amber-300";
  }
  return "text-sky-300";
}

export function SecurityFindingsList({ findings, selectedFindingId, onSelect }: SecurityFindingsListProps) {
  if (findings.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border/70 bg-card/40 p-6 text-sm text-muted-foreground">
        No findings match the current filters. Clear the status or detector filter to restore the full review queue.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {findings.map((finding) => (
        <FindingListItem
          key={finding.id}
          finding={finding}
          isSelected={selectedFindingId === finding.id}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function FindingListItem({
  finding,
  isSelected,
  onSelect,
}: {
  finding: TrustFinding;
  isSelected: boolean;
  onSelect: (findingId: number) => void;
}) {
  const Icon = DETECTOR_ICONS[finding.detector_key] ?? Siren;
  const displayName = finding.suspect_display_name || finding.suspect_actor_id;

  return (
    <button
      type="button"
      onClick={() => onSelect(finding.id)}
      aria-pressed={isSelected}
      className={cn(
        "w-full rounded-2xl border px-4 py-4 text-left transition-all duration-150",
        isSelected
          ? "border-emerald-500/40 bg-emerald-500/8 shadow-[0_0_0_1px_rgba(16,185,129,0.18)]"
          : "border-border/70 bg-card/50 hover:border-border hover:bg-accent/20",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5">
          <div className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            <Icon className="h-3.5 w-3.5" />
            {DETECTOR_LABELS[finding.detector_key] ?? finding.detector_key}
          </div>
          <div className="text-base font-semibold tracking-tight">{displayName}</div>
          <div className="text-sm text-muted-foreground">
            {DETECTOR_DESCRIPTIONS[finding.detector_key]}
          </div>
        </div>
        <Badge variant="outline" className={cn("capitalize", STATUS_STYLES[finding.status])}>
          {formatStatus(finding.status)}
        </Badge>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{finding.channel_id}</span>
            <span>•</span>
            <span className="truncate">{finding.space_id}</span>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className={cn("font-medium", scoreTone(finding.score))}>
              Risk score {finding.score.toFixed(2)}
            </span>
            {finding.notification_count > 0 ? (
              <span>Alerted {finding.notification_count}x</span>
            ) : (
              <span>Not surfaced yet</span>
            )}
          </div>
        </div>
        <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          Updated {formatRelativeTime(finding.updated_at)}
        </div>
      </div>
    </button>
  );
}
