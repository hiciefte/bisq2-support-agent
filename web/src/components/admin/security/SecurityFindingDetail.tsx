"use client";

import type { TrustFinding } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface SecurityFindingDetailProps {
  finding: TrustFinding | null;
  isMutating: boolean;
  onAction: (action: "resolve" | "false-positive" | "suppress" | "mark-benign") => void;
}

export function SecurityFindingDetail({ finding, isMutating, onAction }: SecurityFindingDetailProps) {
  if (!finding) {
    return (
      <div className="rounded-2xl border border-border/70 bg-card/50 p-6 text-sm text-muted-foreground">
        Select a finding to inspect the evidence summary and workflow actions.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/70 p-5 space-y-5">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">{finding.suspect_display_name || finding.suspect_actor_id}</h2>
          <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
            {finding.status}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">{finding.suspect_actor_id}</p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 text-sm">
        <div className="rounded-xl border border-border/70 bg-background/40 p-4">
          <div className="font-medium">Detector</div>
          <div className="mt-1 text-muted-foreground">{finding.detector_key}</div>
        </div>
        <div className="rounded-xl border border-border/70 bg-background/40 p-4">
          <div className="font-medium">Alert surface</div>
          <div className="mt-1 text-muted-foreground">{finding.alert_surface}</div>
        </div>
      </div>

      <div className="rounded-xl border border-border/70 bg-background/40 p-4">
        <div className="font-medium">Evidence summary</div>
        <dl className="mt-3 grid gap-2 text-sm text-muted-foreground">
          {Object.entries(finding.evidence_summary).map(([key, value]) => (
            <div key={key} className="flex flex-wrap items-start justify-between gap-3 border-b border-border/40 pb-2 last:border-b-0 last:pb-0">
              <dt className="font-medium text-foreground/80">{key}</dt>
              <dd className="text-right">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onAction("resolve")} disabled={isMutating}>Resolve</Button>
        <Button size="sm" variant="outline" onClick={() => onAction("false-positive")} disabled={isMutating}>False Positive</Button>
        <Button size="sm" variant="outline" onClick={() => onAction("suppress")} disabled={isMutating}>Suppress</Button>
        <Button size="sm" variant="outline" onClick={() => onAction("mark-benign")} disabled={isMutating}>Mark Benign</Button>
      </div>
    </div>
  );
}
