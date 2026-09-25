export interface StaffContextMetadata {
    context_status: string;
    context_reason: string;
    source_url: string | null;
    staff_thread_url: string | null;
    evidence_version: string;
    generation_version: string;
    late_update_requires_review?: boolean;
    generation_question?: string;
}

export function isStaffContextCase(metadata?: Record<string, unknown> | null): boolean {
    return metadata?.response_kind === "public_context" || metadata?.delivery_audience === "staff_room";
}

function matrixLink(value: unknown): string | null {
    if (typeof value !== "string") return null;
    try {
        const url = new URL(value);
        return url.protocol === "https:" && url.host === "matrix.to"
            && !url.username && !url.password && url.hash.startsWith("#/")
            ? value
            : null;
    } catch {
        return null;
    }
}

export function staffContextMetadata(metadata?: Record<string, unknown> | null): StaffContextMetadata | null {
    if (!isStaffContextCase(metadata) || !metadata) return null;
    const text = (key: string) => typeof metadata[key] === "string" ? metadata[key] as string : "";
    return {
        context_status: text("context_status"),
        context_reason: text("context_reason"),
        source_url: matrixLink(metadata.source_url),
        staff_thread_url: matrixLink(metadata.staff_thread_url),
        evidence_version: text("evidence_version"),
        generation_version: text("generation_version"),
        late_update_requires_review: metadata.incident_late_update_status === "needs_review_no_additional_generation",
        generation_question: text("incident_generation_question"),
    };
}

export function staffContextStatusLabel(status: string): string {
    const labels: Record<string, string> = {
        preparing: "Preparing context",
        awaiting_review: "Awaiting review",
        deferred: "Deferred",
        needs_human: "Needs human attention",
        delivery_pending: "Staff-room delivery pending",
        delivered: "Posted to staff thread",
        delivery_uncertain: "Staff-room delivery uncertain",
        suppressed: "No note posted",
    };
    return labels[status] || "Context status unavailable";
}

export function staffContextReasonLabel(reason: string): string {
    const labels: Record<string, string> = {
        context_preparing: "Preparing a context note for staff.",
        generation_reserved: "Generating a context note from the available evidence.",
        staff_root_reserved: "Preparing the staff review thread.",
        staff_note_reserved: "Posting the context note in the staff review thread.",
        staff_context_delivered: "The context note is available in the staff thread.",
        staff_delivery_requires_reconciliation: "Delivery is uncertain. Check the staff thread before taking further action.",
        processing_interrupted_review_required: "Processing was interrupted. Check the staff thread before taking further action.",
        context_processing_failed: "The context note could not be prepared. Staff review is needed.",
        context_capacity_reached: "The context queue is full. Staff review is needed.",
        context_pii_detected: "The draft may contain personal information and was withheld.",
        high_risk_action: "This question needs a human response.",
        staff_active: "Staff are already active in the conversation, so the note was withheld.",
        recent_bot_reply: "An AI reply is already present, so another note was withheld.",
        source_stale: "The source question is too old for automatic context delivery.",
        source_changed_or_redacted: "The source question changed or was removed. Staff review is needed.",
        source_context_incomplete: "Recent conversation context could not be fully checked.",
        incident_context_capacity_reached: "This incident has more context than can be checked automatically. Staff review is needed.",
        incident_source_context_incomplete: "The complete incident could not be checked against the source messages. Staff review is needed.",
        incident_updated_after_generation: "New incident information arrived after the AI context was prepared. The note was withheld for review.",
        staff_identity_unavailable: "Staff participation could not be checked.",
    };
    if (labels[reason]) return labels[reason];
    if (!/^[a-z][a-z0-9_]*$/.test(reason)) return reason;
    const words = reason.replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1) + ".";
}
