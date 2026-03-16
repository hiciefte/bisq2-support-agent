"use client";

import type { TrustMonitorOpsSnapshot } from "@/components/admin/security/types";

interface SecurityOpsSummaryProps {
  ops: TrustMonitorOpsSnapshot | null;
}

function formatAge(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  }
  return `${Math.round(seconds / 86400)}d`;
}

export function SecurityOpsSummary({ ops }: SecurityOpsSummaryProps) {
  if (!ops) {
    return null;
  }
  const lastRun = ops.last_retention_run;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
      <section className="rounded-2xl border border-border/70 bg-card/50 p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold tracking-tight">Monitoring scope</h2>
          <p className="text-xs text-muted-foreground">
            The detector runs only on configured public support rooms. Staff room traffic is excluded from ingestion.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <MetricCard label="Evidence rows" value={String(ops.evidence_events_count)} hint={`Oldest ${formatAge(ops.oldest_evidence_age_seconds)}`} />
          <MetricCard label="Actor aggregates" value={String(ops.actor_aggregates_count)} hint={`Oldest ${formatAge(ops.oldest_aggregate_age_seconds)}`} />
          <MetricCard label="Findings" value={String(ops.findings_count)} hint={`Oldest ${formatAge(ops.oldest_finding_age_seconds)}`} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Public rooms</div>
            <div className="mt-2 text-sm">
              {ops.monitored_public_rooms.length > 0 ? ops.monitored_public_rooms.join(", ") : "Not configured"}
            </div>
          </div>
          <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Staff room</div>
            <div className="mt-2 text-sm">{ops.staff_room_id || "Not configured"}</div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-card/50 p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold tracking-tight">Retention</h2>
          <p className="text-xs text-muted-foreground">
            Latest purge run and deleted row counts. This is the production check for TTL behavior.
          </p>
        </div>
        <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Last purge</div>
          <div className="mt-2 text-sm">{lastRun ? new Date(lastRun.created_at).toLocaleString() : "No purge recorded yet"}</div>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <MetricCard label="Evidence deleted" value={String(lastRun?.deleted_evidence_events ?? 0)} />
          <MetricCard label="Aggregates deleted" value={String(lastRun?.deleted_actor_aggregates ?? 0)} />
          <MetricCard label="Findings deleted" value={String(lastRun?.deleted_findings ?? 0)} />
          <MetricCard label="Audit rows deleted" value={String((lastRun?.deleted_feedback ?? 0) + (lastRun?.deleted_access_audit ?? 0))} />
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}
