"use client";

import type { TrustFinding } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface SecurityFindingsListProps {
  findings: TrustFinding[];
  selectedFindingId: number | null;
  onSelect: (findingId: number) => void;
}

export function SecurityFindingsList({ findings, selectedFindingId, onSelect }: SecurityFindingsListProps) {
  if (findings.length === 0) {
    return (
      <div className="rounded-2xl border border-border/70 bg-card/50 p-6 text-sm text-muted-foreground">
        No findings match the current filters.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {findings.map((finding) => (
        <button
          key={finding.id}
          type="button"
          onClick={() => onSelect(finding.id)}
          className={cn(
            "w-full rounded-2xl border px-4 py-4 text-left transition-colors",
            selectedFindingId === finding.id
              ? "border-emerald-500/40 bg-emerald-500/5"
              : "border-border/70 bg-card/50 hover:bg-accent/30",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="text-sm font-medium">{finding.detector_key === "staff_name_collision" ? "Staff Name Collision" : "Silent Observer"}</div>
              <div className="text-xs text-muted-foreground">{finding.suspect_display_name || finding.suspect_actor_id}</div>
            </div>
            <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
              {finding.status}
            </Badge>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{finding.channel_id}</span>
            <span>•</span>
            <span>{finding.space_id}</span>
            <span>•</span>
            <span>score {finding.score.toFixed(2)}</span>
          </div>
        </button>
      ))}
    </div>
  );
}
