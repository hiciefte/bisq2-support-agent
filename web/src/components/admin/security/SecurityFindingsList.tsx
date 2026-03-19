"use client";

import { Clock3 } from "lucide-react";
import type { TrustFinding } from "@/components/admin/security/types";
import {
  DETECTOR_DESCRIPTIONS,
  DETECTOR_ICONS,
  DETECTOR_LABELS,
  FALLBACK_DETECTOR_ICON,
  formatRelativeTime,
  formatStatus,
  STATUS_STYLES,
} from "@/components/admin/security/securityUi";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface SecurityFindingsListProps {
  findings: TrustFinding[];
  selectedFindingId: number | null;
  onSelect: (findingId: number) => void;
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
  const Icon = DETECTOR_ICONS[finding.detector_key] ?? FALLBACK_DETECTOR_ICON;
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
