export interface IntakeDispositionStatus {
  deferred_total: number;
  deferred_by_source: Record<string, number>;
  deferred_by_reason: Record<string, number>;
  recent: Array<{
    id: string;
    source: string;
    event_digest: string;
    reason: string;
    last_seen: string;
  }>;
}

function sourceLabel(source: string): string {
  return source === "matrix" ? "Matrix" : source === "bisq2" ? "Bisq 2" : "Support";
}

export function IntakeDispositionNotice({
  status,
  unavailable,
}: {
  status: IntakeDispositionStatus | null;
  unavailable: boolean;
}) {
  if (unavailable) {
    return (
      <p className="rounded-xl border border-border/70 p-4 text-sm text-muted-foreground" role="status">
        Intake status is unavailable. Refresh to check for deferred source messages.
      </p>
    );
  }
  if (!status || status.deferred_total === 0) return null;

  return (
    <div className="space-y-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm" role="status">
      <p className="font-medium">
        {status.deferred_total} source {status.deferred_total === 1 ? "message" : "messages"} deferred
      </p>
      <p className="text-muted-foreground">
        Intake set aside batches with unreadable or incomplete question context before extraction.
        Later messages can continue. These are recorded deferrals, not knowledge candidates.
      </p>
      <p className="text-muted-foreground">
        An operator must review the retained source references before any replay. Retained deferrals are not retried automatically.
        Records expire under the existing retention policy.
      </p>
      <details>
        <summary className="cursor-pointer font-medium">View intake references</summary>
        <p className="mt-2 text-muted-foreground">
          {Object.entries(status.deferred_by_source).map(([source, count]) => `${sourceLabel(source)}: ${count}`).join(" · ")}
        </p>
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {status.recent.map((item) => (
            <li key={item.id}>
              {sourceLabel(item.source)} · {new Date(item.last_seen).toLocaleString()} · Reference {item.event_digest.slice(0, 12)}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
