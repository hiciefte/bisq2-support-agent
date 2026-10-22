import { render, screen } from "@testing-library/react";
import { staffContextMetadata } from "@/lib/staff-context";
import { StaffContextDetails } from "./StaffContextDetails";

test("shows possible connections without asserting common ownership or approval", () => {
    const context = staffContextMetadata({
        response_kind: "public_context",
        context_status: "deferred",
        context_reason: "conversation_membership_unresolved",
        candidate_conversation_ids: [42, 42, 43, "private-id", -1, 2.5, null],
        conversation_pending_candidate_ids: [45],
    });
    expect(context).not.toBeNull();
    render(<StaffContextDetails context={context!} />);
    expect(screen.getByText("Possible earlier cases:").parentElement).toHaveTextContent("Possible earlier cases: #42, #43");
    expect(screen.getByRole("link", { name: "Review case #42" })).toHaveAttribute("href", "/admin/escalations?search=%2342");
    expect(screen.getByRole("link", { name: "Review case #45" })).toHaveAttribute("href", "/admin/escalations?search=%2345");
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
