import { fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { PrivacyWarningModal } from "./privacy-warning-modal";

jest.mock("lucide-react", () => ({
    AlertTriangle: () => <svg data-testid="alert-triangle-icon" />,
    Database: () => <svg data-testid="database-icon" />,
    FileText: () => <svg data-testid="file-text-icon" />,
    KeyRound: () => <svg data-testid="key-round-icon" />,
    Send: () => <svg data-testid="send-icon" />,
    Trash2: () => <svg data-testid="trash-icon" />,
    X: () => <svg data-testid="close-icon" />,
}));

jest.mock("@/components/ui/dialog", () => ({
    Dialog: ({ children, open }: PropsWithChildren<{ open: boolean }>) =>
        open ? <div role="dialog">{children}</div> : null,
    DialogContent: ({ children }: PropsWithChildren) => <div>{children}</div>,
    DialogDescription: ({ children }: PropsWithChildren) => <p>{children}</p>,
    DialogFooter: ({ children }: PropsWithChildren) => <div>{children}</div>,
    DialogHeader: ({ children }: PropsWithChildren) => <div>{children}</div>,
    DialogTitle: ({ children }: PropsWithChildren) => <h2>{children}</h2>,
}));

const STORAGE_KEY = "bisq-privacy-warning-acknowledged-v3";

describe("PrivacyWarningModal", () => {
    beforeEach(() => {
        window.localStorage.clear();
    });

    it("shows the configured retention window and each retention boundary", async () => {
        render(<PrivacyWarningModal retentionDays={14} />);

        expect(await screen.findByText("Privacy & Data Usage Notice")).toBeInTheDocument();
        expect(
            screen.getByText("Local support records older than 14 days are deleted")
        ).toBeInTheDocument();
        expect(
            screen.getByText(/container runtime logs require a separately verified host policy/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                /legacy rows with no provable timestamp can remain pending manual review/
            )
        ).toBeInTheDocument();
        expect(
            screen.getByText("Reviewed knowledge text and aggregate metrics may be retained")
        ).toBeInTheDocument();
        expect(
            screen.getByText("Matrix, Bisq, and provider-held copies are outside local deletion")
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                "Matrix session and local encryption state rotate on the 14-day cadence"
            )
        ).toBeInTheDocument();
    });

    it("records acknowledgement against the corrected notice version", async () => {
        render(<PrivacyWarningModal retentionDays={30} />);

        fireEvent.click(await screen.findByRole("button", { name: "I Understand" }));

        expect(window.localStorage.getItem(STORAGE_KEY)).toBe("true");
        expect(screen.queryByText("Privacy & Data Usage Notice")).not.toBeInTheDocument();
    });
});
