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
    expect(screen.getByText("Possible earlier cases: #42, #43")).toBeInTheDocument();
    expect(screen.getByText("Later messages awaiting review: #45")).toBeInTheDocument();
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
