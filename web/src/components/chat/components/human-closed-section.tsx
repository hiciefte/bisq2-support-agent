/**
 * Inline display shown when an escalated question is closed/dismissed without reply.
 */

import { XCircle } from "lucide-react"

interface HumanClosedSectionProps {
  resolvedAt?: string | null
}

function formatDate(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function HumanClosedSection({ resolvedAt }: HumanClosedSectionProps) {
  return (
    <div className="mt-2 p-3 rounded-lg bg-muted/40 border border-border">
      <div className="flex items-center gap-1.5 mb-1.5">
        <XCircle className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs font-medium text-foreground">
          Escalation Closed
        </span>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        Support closed this request without sending a reply.
      </p>
      {resolvedAt && (
        <p className="text-[10px] text-muted-foreground mt-1.5 tabular-nums">
          {formatDate(resolvedAt)}
        </p>
      )}
    </div>
  )
}
