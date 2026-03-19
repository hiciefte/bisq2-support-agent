"use client";

import type { ReactNode } from "react";
import { Activity, BellRing, Clock3, ShieldAlert } from "lucide-react";
import type { TrustFinding } from "@/components/admin/security/types";
import {
  DETECTOR_ICONS,
  DETECTOR_LABELS,
  FALLBACK_DETECTOR_ICON,
  formatStatus,
  STATUS_STYLES,
} from "@/components/admin/security/securityUi";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SecurityFindingDetailProps {
  finding: TrustFinding | null;
  isMutating: boolean;
  onAction: (action: "resolve" | "false-positive" | "suppress" | "mark-benign") => void;
}

function formatAlertSurface(surface: TrustFinding["alert_surface"]): string {
  return surface.replace(/_/g, " ");
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Never";
  }
  return new Date(value).toLocaleString();
}

export function SecurityFindingDetail({ finding, isMutating, onAction }: SecurityFindingDetailProps) {
  if (!finding) {
    return (
      <div className="rounded-2xl border border-dashed border-border/70 bg-card/40 p-6 text-sm text-muted-foreground">
        Select a finding to inspect the evidence summary and workflow actions.
      </div>
    );
  }

  const Icon = DETECTOR_ICONS[finding.detector_key] ?? FALLBACK_DETECTOR_ICON;
  const displayName = finding.suspect_display_name || finding.suspect_actor_id;

  return (
    <div className="space-y-5 rounded-2xl border border-border/70 bg-card/70 p-5">
      <div className="rounded-2xl border border-border/70 bg-gradient-to-br from-amber-500/10 via-background to-red-500/5 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <Icon className="h-3.5 w-3.5" />
              {DETECTOR_LABELS[finding.detector_key] ?? finding.detector_key}
            </div>
            <div className="text-xl font-semibold tracking-tight">{displayName}</div>
            <p className="text-sm text-muted-foreground">{finding.suspect_actor_id}</p>
          </div>
          <Badge variant="outline" className={cn("capitalize", STATUS_STYLES[finding.status])}>
            {formatStatus(finding.status)}
          </Badge>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <MetaCard
            icon={<ShieldAlert className="h-3.5 w-3.5" />}
            label="Risk score"
            value={finding.score.toFixed(2)}
            hint={finding.score >= 0.9 ? "Immediate review" : finding.score >= 0.75 ? "High confidence" : "Monitor closely"}
          />
          <MetaCard
            icon={<BellRing className="h-3.5 w-3.5" />}
            label="Alert fan-out"
            value={finding.notification_count > 0 ? `${finding.notification_count}x` : "Shadow only"}
            hint={`Last notified ${formatTimestamp(finding.last_notified_at)}`}
          />
          <MetaCard
            icon={<Clock3 className="h-3.5 w-3.5" />}
            label="Last updated"
            value={formatTimestamp(finding.updated_at)}
            hint={`Opened ${formatTimestamp(finding.created_at)}`}
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <MetaPanel label="Room scope" value={`${finding.channel_id} · ${finding.space_id}`} />
        <MetaPanel label="Alert destination" value={formatAlertSurface(finding.alert_surface)} />
      </div>

      <div className="rounded-xl border border-border/70 bg-background/40 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Activity className="h-4 w-4 text-muted-foreground" />
          Why it was flagged
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {Object.entries(finding.evidence_summary).map(([key, value]) => (
            <div key={key} className="rounded-xl border border-border/60 bg-background/60 px-4 py-3">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {humanizeKey(key)}
              </div>
              <div className="mt-2 break-words text-sm font-medium text-foreground/90">
                {String(value)}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border/70 bg-background/35 p-4">
        <div className="text-sm font-medium">Review decision</div>
        <p className="mt-1 text-xs text-muted-foreground">
          Resolve for confirmed risk, mark false positive for detector misses, suppress to silence the actor temporarily, or mark benign for known safe behavior.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onAction("resolve")} disabled={isMutating}>Resolve finding</Button>
          <Button size="sm" variant="outline" onClick={() => onAction("false-positive")} disabled={isMutating}>Mark false positive</Button>
          <Button size="sm" variant="outline" onClick={() => onAction("suppress")} disabled={isMutating}>Suppress actor</Button>
          <Button size="sm" variant="outline" onClick={() => onAction("mark-benign")} disabled={isMutating}>Mark benign</Button>
        </div>
      </div>
    </div>
  );
}

function MetaCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/50 px-4 py-3">
      <div className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-sm font-semibold text-foreground/90">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}

function MetaPanel({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/40 p-4">
      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className="mt-2 text-sm font-medium text-foreground/90">{value}</div>
    </div>
  );
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
