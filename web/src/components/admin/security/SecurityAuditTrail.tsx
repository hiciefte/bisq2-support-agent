"use client";

import type {
  ChatOpsAuditEntry,
  TrustAccessAuditEntry,
} from "@/components/admin/security/types";

interface SecurityAuditTrailProps {
  trustAudit: TrustAccessAuditEntry[];
  chatopsAudit: ChatOpsAuditEntry[];
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

export function SecurityAuditTrail({
  trustAudit,
  chatopsAudit,
}: SecurityAuditTrailProps) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="rounded-2xl border border-border/70 bg-card/50 p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold tracking-tight">Trust-monitor activity</h2>
          <p className="text-xs text-muted-foreground">
            Policy changes and finding actions taken by staff or admins.
          </p>
        </div>
        <AuditList
          rows={trustAudit.map((entry) => ({
            id: entry.id,
            title: entry.action,
            subtitle: `${entry.actor_id} -> ${entry.target_type}:${entry.target_id}`,
            meta: formatTimestamp(entry.created_at),
          }))}
          emptyLabel="No trust-monitor audit events yet."
        />
      </section>

      <section className="rounded-2xl border border-border/70 bg-card/50 p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold tracking-tight">ChatOps activity</h2>
          <p className="text-xs text-muted-foreground">
            Recent shared ChatOps commands across Matrix and Bisq2.
          </p>
        </div>
        <AuditList
          rows={chatopsAudit.map((entry) => ({
            id: entry.id,
            title: `!case ${entry.command_name}`,
            subtitle: `${entry.channel_id} · ${entry.actor_id}${entry.case_id ? ` · #${entry.case_id}` : ""}`,
            meta: `${entry.ok ? "ok" : "error"}${entry.idempotent ? " · idempotent" : ""} · ${formatTimestamp(entry.created_at)}`,
          }))}
          emptyLabel="No ChatOps activity yet."
        />
      </section>
    </div>
  );
}

function AuditList({
  rows,
  emptyLabel,
}: {
  rows: Array<{ id: number; title: string; subtitle: string; meta: string }>;
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border/70 bg-background/30 px-4 py-6 text-sm text-muted-foreground">
        {emptyLabel}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <article
          key={row.id}
          className="rounded-xl border border-border/70 bg-background/40 px-4 py-3"
        >
          <div className="text-sm font-medium">{row.title}</div>
          <div className="mt-1 text-xs text-muted-foreground">{row.subtitle}</div>
          <div className="mt-2 text-xs text-muted-foreground">{row.meta}</div>
        </article>
      ))}
    </div>
  );
}
