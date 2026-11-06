import { Badge } from "@/components/ui/badge";
import { staffContextReasonLabel, staffContextStatusLabel, type StaffContextMetadata } from "@/lib/staff-context";

function CaseLinks({ ids }: { ids: number[] }) {
    return ids.map((id, index) => (
        <span key={id}>
            {index > 0 && ", "}
            <a href={`/admin/escalations?search=%23${id}`} className="text-primary underline underline-offset-4" aria-label={`Review case #${id}`}>
                #{id}
            </a>
        </span>
    ));
}

/** Explain delivery and review evidence without presenting a hold as resolution. */
export function StaffContextDetails({ context }: { context: StaffContextMetadata }) {
    const reviewMessages = context.context_reason === "moderation_review_required"
        ? context.moderation_context_snapshot
        : context.staff_activity_snapshot;
    const decision = context.staff_activity_decision;
    const decisionBasis = {
        incident_member: "Staff activity was linked to a confirmed incident member.",
        native_relation: "Staff activity was linked through a native reply or thread.",
        escalation_service_unavailable: "The conversation lookup was unavailable, so Staff association could not be confirmed.",
        incident_membership_unresolved: "The available evidence did not confirm which conversation the Staff turn belonged to.",
    };
    const decisionPhase = {
        pre_generation: "Recorded before AI generation.",
        pre_root: "Recorded before opening the Staff thread.",
        pre_note: "Recorded before posting the Staff note.",
    };
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
            {context.progress_review_queue && (
                <div role="status" className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                    <p className="font-medium">Unresolved progress reports</p>
                    <p>These reports are collected for review. They have not been confirmed as one incident, and no AI reply is generated from this queue.</p>
                    {context.incident_context_overflow && <p>Only the first and most recent reports are retained here. Review the source conversation for the missing reports.</p>}
                    {context.candidate_conversation_overflow && <p>The possible earlier cases shown are limited; other connections may need review.</p>}
                </div>
            )}
            {decision ? (
                <section aria-label="Recorded Staff association" className="max-w-prose space-y-1 text-sm">
                    <h4 className="font-medium">
                        {decision.reason === "staff_active" ? "Confirmed Staff association" : "Unresolved Staff association"}
                    </h4>
                    <p>{decisionBasis[decision.basis]}</p>
                    <p className="text-muted-foreground">{decisionPhase[decision.phase]}</p>
                    <p className="text-muted-foreground">
                        {decision.coverage === "discussion_unavailable"
                            ? "The observed conversation could not be saved. Its absence does not establish that no Staff turn occurred."
                            : decision.trigger_in_snapshot
                                ? "The triggering Staff turn is included in the bounded observed conversation."
                                : "The bounded observation does not include the triggering Staff turn; the saved discussion alone cannot explain this hold."}
                    </p>
                </section>
            ) : null}
            {Boolean(reviewMessages?.length) && (
                <details className="space-y-2 text-sm">
                    <summary className="cursor-pointer font-medium">Conversation observed when the reply was held</summary>
                    <p className="text-muted-foreground">
                        This is a bounded review snapshot, not proof of what the AI saw or that the
                        question was answered. Nearby unthreaded turns may belong to another conversation.
                    </p>
                    <ol className="space-y-2">
                        {reviewMessages?.map((message, index) => (
                            <li key={index} className="rounded border border-border p-2">
                                <p className="font-medium">
                                    {message.role === "user" ? "Requester" : message.role === "staff" ? `Staff (${message.speaker})` : `Participant (${message.speaker})`}
                                </p>
                                <p className="whitespace-pre-wrap break-words">{message.content}</p>
                            </li>
                        ))}
                    </ol>
                </details>
            )}
            {(Boolean(context.candidate_conversation_ids?.length) ||
                Boolean(context.pending_candidate_ids?.length)) && (
                <div
                    role="status"
                    className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm"
                >
                    <p className="font-medium">Possible conversation connection</p>
                    <p>
                        These cases may belong to the same conversation. Their connection has not
                        been confirmed; keep each participant’s statements separate when reviewing
                        them.
                    </p>
                    {Boolean(context.candidate_conversation_ids?.length) && (
                        <p>
                            Possible earlier cases:{" "}
                            <CaseLinks ids={context.candidate_conversation_ids ?? []} />
                        </p>
                    )}
                    {Boolean(context.pending_candidate_ids?.length) && (
                        <p>
                            Later messages awaiting review:{" "}
                            <CaseLinks ids={context.pending_candidate_ids ?? []} />
                        </p>
                    )}
                    {context.pending_candidate_overflow && <p>Additional later messages could not be linked here. Review the source conversation before responding.</p>}
                </div>
            )}
            {context.late_update_requires_review && (
                <div role="status" className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                    <p className="font-medium">New incident context needs review</p>
                    <p>New messages arrived after this case was last assessed. No additional AI note was generated or sent for those updates. Review the updated conversation before responding.</p>
                    {context.generation_question && (
                        <details>
                            <summary className="cursor-pointer font-medium">Context used for the existing AI attempt</summary>
                            <p className="mt-2 whitespace-pre-wrap break-words">{context.generation_question}</p>
                        </details>
                    )}
                </div>
            )}
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
