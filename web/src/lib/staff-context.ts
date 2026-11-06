export interface StaffContextMetadata {
    context_status: string;
    context_reason: string;
    source_url: string | null;
    staff_thread_url: string | null;
    evidence_version: string;
    generation_version: string;
    late_update_requires_review?: boolean;
    generation_question?: string;
    candidate_conversation_ids?: number[];
    pending_candidate_ids?: number[];
    staff_activity_snapshot?: ReviewContextMessage[];
    staff_activity_decision?: StaffActivityDecision;
    moderation_context_snapshot?: ReviewContextMessage[];
}

interface StaffActivityDecision {
    phase: "pre_generation" | "pre_root" | "pre_note";
    reason: "staff_active" | "staff_context_membership_unresolved";
    basis: "incident_member" | "native_relation" | "escalation_service_unavailable" | "incident_membership_unresolved";
    trigger_in_snapshot: boolean;
    discussion_reason: string | null;
    final_route_reason: string;
    coverage: "bounded_snapshot" | "discussion_unavailable";
}

function staffActivityDecision(
    value: unknown,
    routeReason: string,
    messages: ReviewContextMessage[],
): StaffActivityDecision | undefined {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const record = value as Record<string, unknown>;
    const fields = [
        "version", "phase", "reason", "basis", "trigger_event_sha256",
        "trigger_in_snapshot", "discussion_reason", "final_route_reason", "coverage",
    ];
    if (Object.keys(record).length !== fields.length || fields.some((key) => !Object.hasOwn(record, key))) {
        return undefined;
    }
    const { phase, reason, basis, trigger_in_snapshot, discussion_reason, final_route_reason, coverage } = record;
    if (
        record.version !== 1 ||
        (phase !== "pre_generation" && phase !== "pre_root" && phase !== "pre_note") ||
        (reason !== "staff_active" && reason !== "staff_context_membership_unresolved") ||
        (basis !== "incident_member" && basis !== "native_relation" &&
            basis !== "escalation_service_unavailable" && basis !== "incident_membership_unresolved") ||
        typeof record.trigger_event_sha256 !== "string" ||
        !/^[a-f0-9]{64}$/.test(record.trigger_event_sha256) ||
        typeof trigger_in_snapshot !== "boolean" ||
        (discussion_reason !== null && discussion_reason !== "source_followup_antecedent_unavailable" &&
            discussion_reason !== "source_discussion_capacity_reached" && discussion_reason !== "source_context_changed") ||
        (coverage !== "bounded_snapshot" && coverage !== "discussion_unavailable") ||
        (reason === "staff_active") !== (basis === "incident_member" || basis === "native_relation") ||
        (coverage === "discussion_unavailable") !== (discussion_reason !== null) ||
        (coverage === "discussion_unavailable" && (trigger_in_snapshot || messages.length > 0)) ||
        (trigger_in_snapshot && !messages.some((message) => message.role === "staff")) ||
        final_route_reason !== (discussion_reason ?? reason) ||
        final_route_reason !== routeReason
    ) return undefined;
    // Validate the trigger fingerprint but never expose it as display metadata.
    return { phase, reason, basis, trigger_in_snapshot, discussion_reason, final_route_reason, coverage };
}

interface ReviewContextMessage {
    role: "user" | "staff" | "participant";
    speaker: string;
    content: string;
}

function reviewContextMessages(value: unknown): ReviewContextMessage[] {
    if (!Array.isArray(value)) return [];
    const result: ReviewContextMessage[] = [];
    let remaining = 4000;
    for (const entry of value.slice(0, 10)) {
        if (!entry || typeof entry !== "object") continue;
        const { role, speaker, content } = entry;
        if (
            !["user", "staff", "participant"].includes(role) ||
            typeof content !== "string" || !content.trim() ||
            typeof speaker !== "string" ||
            !/^(?:requester|participant-[1-9][0-9]?)$/.test(speaker) ||
            (role === "user") !== (speaker === "requester")
        ) continue;
        if (content.length > remaining) break;
        result.push({ role, speaker, content });
        remaining -= content.length;
    }
    return result;
}

function caseIds(value: unknown): number[] {
    if (!Array.isArray(value)) return [];
    return [
        ...new Set(
            value.filter(
                (id): id is number =>
                    typeof id === "number" && Number.isSafeInteger(id) && id > 0
            )
        ),
    ].slice(0, 20);
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
    const staffMessages = reviewContextMessages(metadata.staff_activity_snapshot);
    return {
        context_status: text("context_status"),
        context_reason: text("context_reason"),
        source_url: matrixLink(metadata.source_url),
        staff_thread_url: matrixLink(metadata.staff_thread_url),
        evidence_version: text("evidence_version"),
        generation_version: text("generation_version"),
        late_update_requires_review: metadata.incident_late_update_status === "needs_review_no_additional_generation",
        generation_question: text("incident_generation_question"),
        candidate_conversation_ids: caseIds(metadata.candidate_conversation_ids),
        pending_candidate_ids: caseIds(metadata.conversation_pending_candidate_ids),
        staff_activity_snapshot: staffMessages,
        staff_activity_decision: staffActivityDecision(
            metadata.staff_activity_decision, text("context_reason"), staffMessages,
        ),
        moderation_context_snapshot: reviewContextMessages(metadata.moderation_context_snapshot),
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
        moderation_review_required: "A request for personal information needs human moderation review. The automatic reply was withheld.",
        staff_active: "Staff are active in this conversation, so the note is held for review. This does not mean the question is resolved.",
        staff_context_membership_unresolved: "Nearby staff activity could not be linked to a confirmed conversation. The AI note was withheld; review the source context before responding.",
        recent_bot_reply: "An AI reply is already present, so another note was withheld.",
        source_stale: "The source question is too old for automatic context delivery.",
        source_changed_or_redacted: "The source question changed or was removed. Staff review is needed.",
        source_relationship_changed: "The source message no longer matches its recorded conversation link. Staff review is needed.",
        source_context_incomplete: "Recent conversation context could not be fully checked.",
        incident_context_capacity_reached: "This incident has more context than can be checked automatically. Staff review is needed.",
        incident_source_context_incomplete: "The complete incident could not be checked against the source messages. Staff review is needed.",
        incident_updated_after_generation: "New incident information arrived after the AI context was prepared. The note was withheld for review.",
        conversation_membership_unresolved: "This message may continue an existing conversation, but the connection is not confirmed. Review the related cases before responding; no new AI reply was generated for this message.",
        conversation_helper_only: "This appears to be a participant offering advice or asking someone else for diagnostic details. It is held for review instead of being treated as a new support request.",
        source_followup_antecedent_unavailable: "The question or message being answered could not be established. Staff review is needed before generating a reply.",
        source_discussion_capacity_reached: "The conversation is too large to check automatically. Staff review is needed.",
        staff_identity_unavailable: "Staff participation could not be checked.",
    };
    if (labels[reason]) return labels[reason];
    if (!/^[a-z][a-z0-9_]*$/.test(reason)) return reason;
    const words = reason.replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1) + ".";
}
