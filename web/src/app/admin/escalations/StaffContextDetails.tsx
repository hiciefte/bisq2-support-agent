import { Badge } from "@/components/ui/badge";
import { staffContextReasonLabel, staffContextStatusLabel, type StaffContextMetadata } from "@/lib/staff-context";

export function StaffContextDetails({ context }: { context: StaffContextMetadata }) {
    return (
        <section aria-label="Staff context delivery" className="space-y-3 rounded-lg border border-border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-medium">Staff-only context</h3>
                <Badge variant="outline">{staffContextStatusLabel(context.context_status)}</Badge>
            </div>
            <p className="max-w-prose text-sm text-muted-foreground">
                This context is for the staff-room thread and this admin queue. Approval records an
                internal review decision; it cannot publish a reply to the public room.
            </p>
            {context.context_reason && <p className="text-sm">{staffContextReasonLabel(context.context_reason)}</p>}
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                {context.source_url && <a href={context.source_url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-4">View source question</a>}
                {context.staff_thread_url && <a href={context.staff_thread_url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-4">Open staff thread</a>}
            </div>
            {(context.evidence_version || context.generation_version) && (
                <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">Evidence and generation versions</summary>
                    <dl className="mt-2 space-y-2 break-all">
                        {context.evidence_version && <div><dt>Evidence</dt><dd>{context.evidence_version}</dd></div>}
                        {context.generation_version && <div><dt>Generation</dt><dd>{context.generation_version}</dd></div>}
                    </dl>
                </details>
            )}
        </section>
    );
}
