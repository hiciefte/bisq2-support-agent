import { render, screen, within } from "@testing-library/react";
import { staffContextMetadata } from "@/lib/staff-context";
import { StaffContextDetails } from "./StaffContextDetails";

test("progress review queues disclose unconfirmed membership and omitted coverage", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        progress_review_queue: true,
        incident_context_overflow: true,
        candidate_conversation_overflow: true,
    });
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Unresolved progress reports")).toBeInTheDocument();
    expect(screen.getByText(/not been confirmed as one incident/)).toBeInTheDocument();
    expect(screen.getByText(/first and most recent reports/)).toBeInTheDocument();
    expect(screen.getByText(/other connections may need review/)).toBeInTheDocument();
    expect(staffContextMetadata({ response_kind: "public_context", progress_review_queue: "true" })?.progress_review_queue).toBe(false);
});

test("shows possible connections without asserting common ownership or approval", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_status: "deferred",
        context_reason: "conversation_membership_unresolved",
        candidate_conversation_ids: [42, 42, 43, "private-id", -1, 2.5, null],
        conversation_pending_candidate_ids: [45],
        conversation_pending_candidate_overflow: true,
    });
    expect(context).not.toBeNull();
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Possible earlier cases:").parentElement).toHaveTextContent("Possible earlier cases: #42, #43");
    expect(screen.getByRole("link", { name: "Review case #42" })).toHaveAttribute("href", "/admin/escalations?search=%2342");
    expect(screen.getByRole("link", { name: "Review case #45" })).toHaveAttribute("href", "/admin/escalations?search=%2345");
    expect(screen.getByText(/Additional later messages could not be linked here/)).toBeInTheDocument();
    expect(screen.getByText(/connection has not been confirmed/)).toBeInTheDocument();
    expect(screen.getByText(/no new AI reply was generated for this message/)).toBeInTheDocument();
    expect(screen.queryByText(/private-id/)).not.toBeInTheDocument();
});

test("old cases do not acquire an invented membership warning", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_status: "delivered",
        context_reason: "staff_context_delivered",
        conversation_pending_candidate_ids: { id: 42 },
    });
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Posted to staff thread")).toBeInTheDocument();
    expect(screen.queryByText("Possible conversation connection")).not.toBeInTheDocument();
});


test("uncertain staff activity asks for review without claiming the case is answered", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_status: "deferred",
        context_reason: "staff_context_membership_unresolved",
    });
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText(/Nearby staff activity could not be linked/)).toBeInTheDocument();
    expect(screen.queryByText(/Staff are active in this conversation/)).not.toBeInTheDocument();
    expect(screen.getByText(/The AI note was withheld/)).toBeInTheDocument();
    expect(screen.queryByText(/no AI reply was generated/)).not.toBeInTheDocument();
});

test("held discussion preserves speakers and separates review context from model input", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_status: "deferred",
        context_reason: "staff_active",
        staff_activity_snapshot: [
            { role: "user", speaker: "requester", content: "The update failed." },
            { role: "staff", speaker: "participant-1", content: "Which version is installed?" },
            { role: "participant", speaker: "participant-2", content: "<script>synthetic()</script>" },
            { role: "staff", speaker: "requester", content: "Invalid attribution" },
            { role: "participant", speaker: "@private:example.test", content: "Invalid identity" },
        ],
    });
    const { container } = render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Requester")).toBeInTheDocument();
    expect(screen.getByText("Staff (participant-1)")).toBeInTheDocument();
    expect(screen.getByText("Which version is installed?")).toBeInTheDocument();
    expect(screen.getByText(/not proof of what the AI saw/)).toBeInTheDocument();
    expect(screen.getByText(/does not mean the question is resolved/)).toBeInTheDocument();
    expect(screen.queryByText("Invalid attribution")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid identity")).not.toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>synthetic()</script>")).toBeInTheDocument();
});

test("held snapshots remain bounded and absent on old cases", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        staff_activity_snapshot: Array.from({ length: 12 }, () => ({
            role: "user", speaker: "requester", content: "x".repeat(500),
        })),
    });
    expect(context?.staff_activity_snapshot).toHaveLength(8);
    expect(staffContextMetadata({ response_kind: "public_context" })?.staff_activity_snapshot).toEqual([]);
});

test("moderation review displays its observation instead of an older staff hold", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_reason: "moderation_review_required",
        staff_activity_snapshot: [
            { role: "staff", speaker: "participant-1", content: "Older staff hold" },
        ],
        moderation_context_snapshot: [
            { role: "user", speaker: "requester", content: "Synthetic moderation context" },
        ],
    });
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Synthetic moderation context")).toBeInTheDocument();
    expect(screen.queryByText("Older staff hold")).not.toBeInTheDocument();
    expect(screen.getByText(/needs human moderation review/)).toBeInTheDocument();
});

const triggerFingerprint = "a".repeat(64);
const confirmedDecision = {
    version: 1,
    phase: "pre_generation",
    reason: "staff_active",
    basis: "incident_member",
    trigger_event_sha256: triggerFingerprint,
    trigger_in_snapshot: true,
    discussion_reason: null,
    final_route_reason: "staff_active",
    coverage: "bounded_snapshot",
};

function decisionContext(decision: unknown = confirmedDecision, overrides: Record<string, unknown> = {}) {
    return staffContextMetadata({
        response_kind: "public_context",
        context_status: "deferred",
        context_reason: "staff_active",
        staff_activity_snapshot: [
            { role: "staff", speaker: "participant-1", content: "Synthetic Staff clarification" },
        ],
        staff_activity_decision: decision,
        ...overrides,
    })!;
}

test.each([
    ["incident_member", "Staff activity was linked to a confirmed incident member."],
    ["native_relation", "Staff activity was linked through a native reply or thread."],
])("confirmed %s decision stays distinct from observed text", (basis, explanation) => {
    const context = decisionContext({ ...confirmedDecision, basis });
    const { container } = render(<StaffContextDetails context={context} />);
    const decision = screen.getByRole("region", { name: "Recorded Staff association" });
    expect(within(decision).getByRole("heading", { name: "Confirmed Staff association" })).toBeInTheDocument();
    expect(within(decision).getByText(explanation)).toBeInTheDocument();
    expect(within(decision).getByText("Recorded before AI generation.")).toBeInTheDocument();
    expect(within(decision).getByText(/triggering Staff turn is included/)).toBeInTheDocument();
    expect(within(decision).queryByText("Synthetic Staff clarification")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic Staff clarification")).toBeInTheDocument();
    expect(container).not.toHaveTextContent(triggerFingerprint);
    expect(context.staff_activity_decision).not.toHaveProperty("trigger_event_sha256");
});

test.each([
    ["escalation_service_unavailable", "The conversation lookup was unavailable, so Staff association could not be confirmed."],
    ["incident_membership_unresolved", "The available evidence did not confirm which conversation the Staff turn belonged to."],
])("unresolved %s decision explains the missing trigger without inventing ownership", (basis, explanation) => {
    const context = decisionContext({
        ...confirmedDecision,
        phase: "pre_note",
        reason: "staff_context_membership_unresolved",
        basis,
        trigger_in_snapshot: false,
        final_route_reason: "staff_context_membership_unresolved",
    }, {
        context_reason: "staff_context_membership_unresolved",
        staff_activity_snapshot: [{ role: "user", speaker: "requester", content: "Synthetic update" }],
    });
    render(<StaffContextDetails context={context} />);
    expect(screen.getByRole("heading", { name: "Unresolved Staff association" })).toBeInTheDocument();
    expect(screen.getByText(explanation)).toBeInTheDocument();
    expect(screen.getByText("Recorded before posting the Staff note.")).toBeInTheDocument();
    expect(screen.getByText(/does not include the triggering Staff turn/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Confirmed Staff association" })).not.toBeInTheDocument();
});

test.each([
    "source_followup_antecedent_unavailable",
    "source_discussion_capacity_reached",
    "source_context_changed",
])("unavailable discussion retains the distinct association decision for %s", (discussionReason) => {
    const context = decisionContext({
        ...confirmedDecision,
        phase: "pre_root",
        trigger_in_snapshot: false,
        discussion_reason: discussionReason,
        final_route_reason: discussionReason,
        coverage: "discussion_unavailable",
    }, { context_reason: discussionReason, staff_activity_snapshot: [] });
    render(<StaffContextDetails context={context} />);
    expect(screen.getByRole("heading", { name: "Confirmed Staff association" })).toBeInTheDocument();
    expect(screen.getByText("Recorded before opening the Staff thread.")).toBeInTheDocument();
    expect(screen.getByText(/observed conversation could not be saved/)).toBeInTheDocument();
    expect(screen.queryByText("Conversation observed when the reply was held")).not.toBeInTheDocument();
});

test.each([
    null,
    [],
    "staff_active",
    { ...confirmedDecision, version: 2 },
    { ...confirmedDecision, version: "1" },
    { ...confirmedDecision, phase: "after_delivery" },
    { ...confirmedDecision, reason: "arbitrary_reason" },
    { ...confirmedDecision, basis: "nearby_staff" },
    { ...confirmedDecision, basis: "incident_membership_unresolved" },
    { ...confirmedDecision, trigger_event_sha256: "$raw-event:example.test" },
    { ...confirmedDecision, trigger_event_sha256: "a".repeat(63) },
    { ...confirmedDecision, trigger_in_snapshot: "true" },
    { ...confirmedDecision, discussion_reason: "unknown_reason" },
    { ...confirmedDecision, discussion_reason: "source_context_changed" },
    { ...confirmedDecision, final_route_reason: "source_context_changed" },
    { ...confirmedDecision, coverage: "complete" },
    { ...confirmedDecision, coverage: "discussion_unavailable" },
    { ...confirmedDecision, extra: "unexpected-field" },
    { ...confirmedDecision, trigger_event_sha256: undefined },
])("malformed audit %# is ignored without changing the observed discussion", (audit) => {
    const context = decisionContext(audit);
    render(<StaffContextDetails context={context} />);
    expect(context.staff_activity_decision).toBeUndefined();
    expect(screen.queryByRole("region", { name: "Recorded Staff association" })).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic Staff clarification")).toBeInTheDocument();
});

test("partial, stale and snapshot-inconsistent audit records are ignored", () => {
    const partial: Partial<typeof confirmedDecision> = { ...confirmedDecision };
    delete partial.phase;
    expect(decisionContext(partial).staff_activity_decision).toBeUndefined();
    expect(decisionContext(confirmedDecision, { context_reason: "moderation_review_required" }).staff_activity_decision).toBeUndefined();
    expect(decisionContext(confirmedDecision, { staff_activity_snapshot: [] }).staff_activity_decision).toBeUndefined();
    expect(decisionContext(confirmedDecision, {
        staff_activity_snapshot: [{ role: "staff", speaker: "requester", content: "Invalid attribution" }],
    }).staff_activity_decision).toBeUndefined();
    expect(decisionContext({
        ...confirmedDecision,
        trigger_in_snapshot: false,
        discussion_reason: "source_context_changed",
        final_route_reason: "source_context_changed",
        coverage: "discussion_unavailable",
    }, { context_reason: "source_context_changed" }).staff_activity_decision).toBeUndefined();
});

test("old Staff holds have no invented audit explanation", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_reason: "staff_active",
        staff_activity_snapshot: [
            { role: "staff", speaker: "participant-1", content: "Synthetic Staff clarification" },
        ],
    })!;
    expect(context.staff_activity_decision).toBeUndefined();
    render(<StaffContextDetails context={context} />);
    expect(screen.queryByRole("region", { name: "Recorded Staff association" })).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic Staff clarification")).toBeInTheDocument();
});

test("snapshot uses the backend Unicode budget and retains the last Staff turn", () => {
    const context = decisionContext(confirmedDecision, {
        staff_activity_snapshot: [
            { role: "staff", speaker: "participant-1", content: "x".repeat(3998) },
            { role: "staff", speaker: "participant-2", content: "👍👍" },
        ],
    });
    expect(context.staff_activity_snapshot).toHaveLength(2);
    expect(context.staff_activity_decision?.trigger_in_snapshot).toBe(true);
});

test.each([
    { role: "staff", speaker: "participant-2", content: "x".repeat(4000) },
    { role: "staff", speaker: "requester", content: "Invalid attribution" },
])("discarded turns prevent an unsupported trigger-inclusion claim", (lastTurn) => {
    const context = decisionContext(confirmedDecision, {
        staff_activity_snapshot: [
            { role: "staff", speaker: "participant-1", content: "Earlier Staff turn" },
            lastTurn,
        ],
    });
    expect(context.staff_activity_snapshot).toHaveLength(1);
    expect(context.staff_activity_decision).toBeUndefined();
    render(<StaffContextDetails context={context} />);
    expect(screen.queryByText(/triggering Staff turn is included/)).not.toBeInTheDocument();
});
